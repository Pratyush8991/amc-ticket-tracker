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
from datetime import date
from urllib.parse import quote, unquote

from ..client import DEFAULT_TIMEOUT, QUEUE_HOST
from ..errors import (
    AccessBlocked,
    FetchError,
    FetchUnavailable,
    QueueWalled,
    RateLimited,
    ShapeChanged,
)
from .parse import parse_discovery, parse_seat_response, parse_theatre_page
from .queries import DISCOVERY_QUERY, THEATRES_QUERY, seat_query

GRAPHQL_URL = "https://graph.amctheatres.com/"
WARMUP_URL = "https://www.amctheatres.com/"

# The browser's ordinary cross-origin headers are what authorize the call — cookies +
# Origin/Referer, never a vendor key or other custom header (research memo, door 1).
GRAPHQL_HEADERS = {
    "Accept": "application/json",
    "Origin": "https://www.amctheatres.com",
    "Referer": "https://www.amctheatres.com/",
}


def open_graphql_session():
    """A curl_cffi session impersonating a real browser, its cookie jar warmed.

    The warm-up GET on www earns the Cloudflare/session cookies that authorize the
    graph host. Thin untested shell, exactly like requests.Session on the RSC side.
    """
    from curl_cffi import requests as curl_requests  # deferred: loads the native lib

    session = curl_requests.Session(impersonate="chrome")
    session.get(WARMUP_URL, timeout=DEFAULT_TIMEOUT)
    return session


def _graphql(session, query, timeout, variables=None, showtime_id=None):
    """POST one query and classify the answer, mirroring the RSC client's contract:
    the return value is a trustworthy GraphQL payload, everything else raises."""
    try:
        response = session.post(
            GRAPHQL_URL,
            json={"query": query, "variables": variables or {}},
            headers=GRAPHQL_HEADERS,
            timeout=timeout,
        )
    except FetchError:
        raise
    except Exception as e:  # curl_cffi's exception tree — the one narrow broad-catch
        raise FetchUnavailable(f"graphql request failed: {e}", showtime_id) from e
    return _classify(response, showtime_id)


def _classify(response, showtime_id):
    if QUEUE_HOST in (response.url or ""):
        raise QueueWalled(
            "the GraphQL host redirected into the Queue-it waiting room", showtime_id
        )
    if response.status_code == 403:
        raise AccessBlocked("403 refused at the GraphQL host", showtime_id)
    if response.status_code == 429:
        raise RateLimited("HTTP 429 from the GraphQL host — asking too often", showtime_id)
    if not response.ok:
        raise FetchUnavailable(
            f"HTTP {response.status_code} from the GraphQL host", showtime_id
        )
    try:
        payload = response.json()
    except ValueError as e:
        raise ShapeChanged(
            "graphql: response is not JSON (a challenge or interstitial page?)",
            showtime_id,
        ) from e
    errors = payload.get("errors") if isinstance(payload, dict) else None
    if errors:
        said = "; ".join(str(e.get("message", e)) for e in errors[:3])
        raise ShapeChanged(f"graphql: server rejected the query: {said}", showtime_id)
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

    The default `query="AMC"` matches every location, making this a full
    enumeration; pass `coordinates` / attribute filters for a narrower picker
    search. Pages through the Relay connection via endCursor until exhausted.
    """
    owned = session is None
    session = session or open_graphql_session()
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
    theatres = []
    try:
        while True:
            payload = _graphql(session, THEATRES_QUERY, timeout, variables=dict(variables))
            page, has_next, end_cursor = parse_theatre_page(payload)
            theatres.extend(page)
            if not has_next:
                return tuple(theatres)
            if not end_cursor:
                raise ShapeChanged("graphql theatres: hasNextPage without an endCursor")
            variables["after"] = end_cursor
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
    session.cookies.set("session", quote(json.dumps(fields)), domain=".amctheatres.com")


def discover_showtimes(theatre_slug, business_date, session=None, timeout=DEFAULT_TIMEOUT):
    """Enumerate one theatre's Showtimes for one business date — Discovery.

    The sole way Showtimes enter the Registry (ADR-0005). Rows come back
    pre-enriched (movie, format, start time, auditorium, theatre), so no second
    fetch follows. The business date is cookie-driven, not an argument of the query;
    callers loop forward day by day and union the IDs.
    """
    owned = session is None
    session = session or open_graphql_session()
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
    session = session or open_graphql_session()
    try:
        payload = _graphql(
            session, seat_query(showtime_id), timeout, showtime_id=showtime_id
        )
        return parse_seat_response(payload, showtime_id)
    finally:
        if owned:
            session.close()
