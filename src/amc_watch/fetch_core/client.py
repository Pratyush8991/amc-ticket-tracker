"""The one outbound edge of the whole system: GET a Seat Page.

Transport behavior here is load-bearing and ported intact from the proven single-user
watcher (ADR-0003): python-requests with a browser User-Agent passes AMC's Cloudflare
hardening where curl 403s. A fresh Session per fetch (requests.Session is not guaranteed
thread-safe) and a browser Accept/Accept-Language pair are part of that behavior, not
incidental style. Never replace this with a headless browser — AMC flags automation
(ADR-0001).

This module is also the seam the test suite fakes: tests inject a session that serves
recorded RSC payloads, so fetch → parse runs for real in every test.
"""

import requests

from .errors import (
    AccessBlocked,
    QueueWalled,
    SeatPageUnavailable,
    ShowtimeNotFound,
)
from .parse import parse_seat_page

SEAT_PAGE_URL = "https://www.amctheatres.com/showtimes/{showtime_id}/seats"
QUEUE_HOST = "queue.amctheatres.com"
DEFAULT_TIMEOUT = 25

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/143.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}


def seat_page_url(showtime_id):
    """The canonical Seat Page URL — also what an Alert deep-links to."""
    return SEAT_PAGE_URL.format(showtime_id=showtime_id)


def _classify(response, showtime_id):
    """Turn a response that is not a usable Seat Page into the right error.

    Ordering matters: the queue check comes first because Queue-it answers 200 once the
    redirect is followed, so status alone would read it as success.
    """
    if QUEUE_HOST in (response.url or "") or any(
        QUEUE_HOST in (r.headers.get("location") or "") for r in response.history
    ):
        raise QueueWalled(
            f"redirected into the Queue-it waiting room ({response.url})", showtime_id
        )
    if response.status_code == 403:
        raise AccessBlocked("403 refused by AMC/Cloudflare", showtime_id)
    if response.status_code == 404:
        raise ShowtimeNotFound("404 — no such showtime", showtime_id)
    if not response.ok:
        raise SeatPageUnavailable(f"HTTP {response.status_code}", showtime_id)


def fetch_seat_page(showtime_id, session=None, timeout=DEFAULT_TIMEOUT):
    """Fetch and parse one Seat Page.

    Returns a SeatPage. Raises a SeatPageError subclass if AMC did not give us a
    trustworthy answer — a Seat Page with every seat sold is a *successful* fetch that
    returns a SeatPage with no bookable seats, never an exception.
    """
    owned = session is None
    session = session or requests.Session()
    try:
        try:
            response = session.get(
                seat_page_url(showtime_id), headers=HEADERS, timeout=timeout
            )
        except requests.RequestException as e:
            raise SeatPageUnavailable(f"request failed: {e}", showtime_id) from e
        _classify(response, showtime_id)
        return parse_seat_page(response.text)
    finally:
        if owned:
            session.close()
