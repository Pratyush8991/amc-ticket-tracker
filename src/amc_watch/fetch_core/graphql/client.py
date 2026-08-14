"""The second outbound edge: POST GraphQL to graph.amctheatres.com (ADR-0005).

Transport behavior here is load-bearing, and it is *not* the RSC client's: the GraphQL
host 403s plain python-requests AND curl, so it is reached with curl_cffi's browser
TLS/JA3 impersonation plus a cookie jar warmed on www.amctheatres.com. The lesson of
ADR-0003 holds per host — never swap either backend's transport casually, and never a
headless browser.

This module is the seam the test suite fakes: tests inject a curl_cffi-shaped session
serving recorded GraphQL JSON, so query building → classification → parse runs real.
"""

from ..client import DEFAULT_TIMEOUT
from .parse import parse_seat_response
from .queries import seat_query

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


def _graphql(session, query, timeout):
    response = session.post(
        GRAPHQL_URL, json={"query": query}, headers=GRAPHQL_HEADERS, timeout=timeout
    )
    return response.json()


def fetch_seat_page_graphql(showtime_id, session=None, timeout=DEFAULT_TIMEOUT):
    """Read one Showtime's seats over GraphQL.

    Yields the same SeatPage the RSC parser does — the two backends are
    interchangeable at the seat-read seam, which is what makes the RSC fetcher a
    genuine fallback. A sold-out house is a successful read, never an exception.
    """
    owned = session is None
    session = session or open_graphql_session()
    try:
        payload = _graphql(session, seat_query(showtime_id), timeout)
        return parse_seat_response(payload, showtime_id)
    finally:
        if owned:
            session.close()
