"""The second outbound edge: POST GraphQL to graph.amctheatres.com (ADR-0005).

Transport behavior here is load-bearing, and it is *not* the RSC client's: the GraphQL
host 403s plain python-requests AND curl, so it is reached with curl_cffi's browser
TLS/JA3 impersonation plus a cookie jar warmed on www.amctheatres.com. The lesson of
ADR-0003 holds per host — never swap either backend's transport casually, and never a
headless browser.

This module is the seam the test suite fakes: tests inject a curl_cffi-shaped session
serving recorded GraphQL JSON, so query building → classification → parse runs real.
"""

import json
from contextlib import contextmanager
from datetime import date
from urllib.parse import quote, unquote

from ..client import DEFAULT_TIMEOUT, QUEUE_HOST
from ..errors import (
    AccessBlocked,
    FetchUnavailable,
    QueueWalled,
    RateLimited,
    ShapeChanged,
)
from .parse import parse_discovery, parse_seat_response, parse_theatre_page
from .queries import DISCOVERY_QUERY, THEATRES_QUERY, seat_query

GRAPHQL_URL = "https://graph.amctheatres.com/"
WARMUP_URL = "https://www.amctheatres.com/"
COOKIE_DOMAIN = ".amctheatres.com"

# The browser's ordinary cross-origin headers are what authorize the call — cookies +
# Origin/Referer, never a vendor key or other custom header (research memo, door 1).
GRAPHQL_HEADERS = {
    "Accept": "application/json",
    "Origin": "https://www.amctheatres.com",
    "Referer": "https://www.amctheatres.com/",
}

# A theatre connection is a few hundred rows over tens of pages; past this many the
# walk is not paging, it is looping, and every extra lap is spent Polling Budget.
MAX_THEATRE_PAGES = 200


def _send(what, showtime_id, call, *args, **kwargs):
    """Run one curl_cffi call, converting its exception tree into the taxonomy."""
    try:
        return call(*args, **kwargs)
    except Exception as e:  # curl_cffi's own tree — the one narrow broad-catch
        raise FetchUnavailable(f"{what} failed: {e}", showtime_id) from e


def _classify_transport(response, showtime_id, what):
    """Transport-level verdict, shared by the warm-up GET and the GraphQL POST."""
    if QUEUE_HOST in (response.url or ""):
        raise QueueWalled(f"{what} was redirected into the Queue-it waiting room", showtime_id)
    if response.status_code == 403:
        raise AccessBlocked(f"403 refused at {what}", showtime_id)
    if response.status_code == 429:
        raise RateLimited(f"HTTP 429 from {what} — asking too often", showtime_id)


def open_graphql_session(timeout=DEFAULT_TIMEOUT):
    """A curl_cffi session impersonating a real browser, its cookie jar warmed.

    The warm-up GET on www earns the Cloudflare/session cookies that authorize the
    graph host, so a warm-up that fails or is refused is a failed fetch, not a
    detail — on a fresh box it is the *likeliest* failure, and the operator must get
    the ADR-0004 remedy rather than a traceback.
    """
    from curl_cffi import requests as curl_requests  # deferred: loads the native lib

    session = curl_requests.Session(impersonate="chrome")
    try:
        response = _send(
            "the cookie-jar warm-up", None, session.get, WARMUP_URL, timeout=timeout
        )
        _classify_transport(response, None, "the cookie-jar warm-up")
        if not response.ok:
            raise FetchUnavailable(
                f"HTTP {response.status_code} warming the cookie jar at {WARMUP_URL}"
            )
    except BaseException:
        session.close()
        raise
    return session


@contextmanager
def graphql_session(timeout=DEFAULT_TIMEOUT):
    """One warmed session for a batch of queries.

    Every operation here opens (and warms, costing a request) its own session when
    given none, so a caller looping over days or showtimes should hold one instead:

        with graphql_session() as session:
            for day in days:
                discover_showtimes(slug, day, session=session)
    """
    session = open_graphql_session(timeout=timeout)
    try:
        yield session
    finally:
        session.close()


def _graphql(session, query, timeout, variables=None, showtime_id=None):
    """POST one query and classify the answer, mirroring the RSC client's contract:
    the return value is a trustworthy GraphQL payload, everything else raises."""
    response = _send(
        "the graphql request",
        showtime_id,
        session.post,
        GRAPHQL_URL,
        json={"query": query, "variables": variables or {}},
        headers=GRAPHQL_HEADERS,
        timeout=timeout,
    )
    return _classify(response, showtime_id)


def _said(errors):
    """AMC's own words out of a GraphQL `errors` value, whatever shape it arrived in.

    Defensive because this runs on the malformed-response path: a formatter that
    assumes a list of dicts crashes exactly when the response is least trustworthy.
    """
    if not isinstance(errors, (list, tuple)):
        errors = [errors]
    said = []
    for error in list(errors)[:3]:
        message = error.get("message", error) if isinstance(error, dict) else error
        said.append(str(message))
    return "; ".join(said)


def _classify(response, showtime_id):
    _classify_transport(response, showtime_id, "the GraphQL host")
    try:
        payload = response.json()
    except ValueError as e:
        if not response.ok:
            raise FetchUnavailable(
                f"HTTP {response.status_code} from the GraphQL host", showtime_id
            ) from e
        raise ShapeChanged(
            "graphql: response is not JSON (a challenge or interstitial page?)",
            showtime_id,
        ) from e
    errors = payload.get("errors") if isinstance(payload, dict) else None
    if errors:
        # GraphQL servers ride validation errors on an HTTP 400 (observed live
        # 2026-08-14) — either way it means our query no longer fits the schema, and
        # the operator gets AMC's words, not a mute status code.
        raise ShapeChanged(
            f"graphql: server rejected the query: {_said(errors)}", showtime_id
        )
    if not response.ok:
        raise FetchUnavailable(
            f"HTTP {response.status_code} from the GraphQL host", showtime_id
        )
    return payload


def enumerate_theatres(
    session=None,
    *,
    query="AMC",
    coordinates=None,
    include_attributes=None,
    exclude_attributes=None,
    brand=None,
    operation=None,
    page_size=50,
    timeout=DEFAULT_TIMEOUT,
):
    """Enumerate or search Theatres through the viewer.theatres connection.

    Pages through the Relay connection via endCursor until exhausted. The default
    `query="AMC"` is a free-text search that matches AMC-branded locations — the
    broadest enumeration this endpoint offers, but a *search*, not a guaranteed
    census: a location whose searchable text omits "AMC" will not appear. Pass
    `coordinates` / attribute filters for a narrower picker search.
    """
    owned = session is None
    session = session or open_graphql_session(timeout=timeout)
    variables = {
        "query": query,
        "coordinates": coordinates,
        "includeAttributes": include_attributes,
        "excludeAttributes": exclude_attributes,
        "brand": brand,
        "operation": operation,
        "first": page_size,
        "after": None,
    }
    theatres, seen_cursors = [], set()
    try:
        for _ in range(MAX_THEATRE_PAGES):
            payload = _graphql(session, THEATRES_QUERY, timeout, variables=dict(variables))
            page, has_next, end_cursor = parse_theatre_page(payload)
            theatres.extend(page)
            if not has_next:
                return tuple(theatres)
            if not end_cursor:
                raise ShapeChanged("graphql theatres: hasNextPage without an endCursor")
            if end_cursor in seen_cursors:
                # A cursor that repeats never advances: the walk would POST the same
                # page forever, which is how a polite client becomes a blocked one.
                raise ShapeChanged(
                    f"graphql theatres: endCursor {end_cursor!r} repeated — pagination "
                    "is not advancing"
                )
            seen_cursors.add(end_cursor)
            variables["after"] = end_cursor
        raise ShapeChanged(
            f"graphql theatres: still paging after {MAX_THEATRE_PAGES} pages — "
            "refusing to keep asking"
        )
    finally:
        if owned:
            session.close()


_EPOCH = date(1970, 1, 1)


def _patch_business_date(session, business_date):
    """Point the session cookie's business date at the target day.

    AMC reads the listing date from the URL-encoded JSON `session` cookie
    (`nowInDays` = days since the Unix epoch, plus `lastViewedDate`), so the patch
    happens in the warmed jar before each discovery POST. Every other field the
    warm-up earned is preserved — the cookie is also what authorizes the host.
    """
    raw = session.cookies.get("session")
    try:
        fields = json.loads(unquote(raw)) if raw else {}
    except ValueError:
        fields = {}
    if not isinstance(fields, dict):
        fields = {}
    fields["nowInDays"] = (business_date - _EPOCH).days
    fields["lastViewedDate"] = f"{business_date:%Y%m%d}T12:00:00.000Z"
    # Drop the warm-up's own `session` entry first: the jar keys on (domain, path,
    # name), so setting ours beside a host-only one leaves *two* session cookies on
    # the wire and lets AMC pick which date it honors.
    session.cookies.delete("session")
    session.cookies.set("session", quote(json.dumps(fields)), domain=COOKIE_DOMAIN)


def discover_showtimes(theatre_slug, business_date, session=None, timeout=DEFAULT_TIMEOUT):
    """Enumerate one theatre's Showtimes for one business date — Discovery.

    The sole way Showtimes enter the Registry (ADR-0005). Rows come back
    pre-enriched (movie, format, start time, auditorium, theatre), so no second
    fetch follows. The business date is cookie-driven, not an argument of the query;
    callers loop forward day by day and union the IDs — holding one `graphql_session`
    across that loop, so the jar is warmed once rather than once per day.
    """
    owned = session is None
    session = session or open_graphql_session(timeout=timeout)
    try:
        _patch_business_date(session, business_date)
        payload = _graphql(
            session, DISCOVERY_QUERY, timeout, variables={"slug": theatre_slug}
        )
        return parse_discovery(payload, theatre_slug)
    finally:
        if owned:
            session.close()


def fetch_seat_page_graphql(showtime_id, session=None, timeout=DEFAULT_TIMEOUT):
    """Read one Showtime's seats over GraphQL.

    Yields the same SeatPage the RSC parser does — the two backends are
    interchangeable at the seat-read seam, which is what makes the RSC fetcher a
    genuine fallback. A sold-out house is a successful read, never an exception.
    """
    owned = session is None
    session = session or open_graphql_session(timeout=timeout)
    try:
        payload = _graphql(
            session, seat_query(showtime_id), timeout, showtime_id=showtime_id
        )
        return parse_seat_response(payload, showtime_id)
    finally:
        if owned:
            session.close()
