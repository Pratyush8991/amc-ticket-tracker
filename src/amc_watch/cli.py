"""Operator command line.

    amc-watch smoke-test [--showtime-id ID] [--theatre-slug SLUG]

The smoke test is the first act on any new box (ADR-0004, amended by ADR-0005): one GET
of a known Seat Page *and* one curl_cffi discovery POST at the GraphQL host, pass or
fail with the reason per surface. Every proof that either surface accepts this traffic
was taken from a residential IP, so until both pass on a given machine, nothing else
built on it can be trusted to work.
"""

import argparse
import os
import sys
from datetime import date

from .fetch_core import (
    AccessBlocked,
    DiscoveryIncomplete,
    FetchError,
    QueueWalled,
    RateLimited,
    ShapeChanged,
    ShowtimeNotFound,
    TheatreNotFound,
    discover_showtimes,
    fetch_seat_page,
    seat_page_url,
)
from .fetch_core.graphql import GRAPHQL_URL

# A Seat Page known to exist. Showtimes pass, so this rots by design — hence
# --showtime-id and AMC_SMOKE_TEST_SHOWTIME_ID. A ShowtimeNotFound from the default is a
# stale constant, not a blocked box, and the failure text says so.
#
# Note the ID waves are not contiguous with each other: Aug 9 was 1446969xx and Aug 15 is
# 1453774xx. Do not try to guess a fresh ID by probing outward from a stale one — that is
# the range-probing ADR-0001 rejected, and it would not even work.
DEFAULT_SHOWTIME_ID = "145377422"  # The Odyssey, IMAX 70mm, Metreon 16, Sat 2026-08-15

# Theatre slugs, by contrast, are stable for the life of a theatre — this one rots only
# if AMC Metreon 16 closes. An empty discovery still passes: reach is the question.
DEFAULT_THEATRE_SLUG = "amc-metreon-16"

REMEDIES = {
    QueueWalled: (
        "This box was put in the Queue-it waiting room. It is often intermittent — "
        "retry a few times. If it never clears, treat it as blocked."
    ),
    AccessBlocked: (
        "AMC refused this box outright. If this is a fresh cloud box, this is the "
        "ADR-0004 contingency: re-home the poller to a residential connection. "
        "Do not build on this box until it passes."
    ),
    ShowtimeNotFound: (
        "That showtime no longer exists — almost certainly a stale default rather than "
        "a network problem. Re-run with --showtime-id <a currently-listed showtime>."
    ),
    TheatreNotFound: (
        "No theatre lives at that slug — almost certainly a stale default rather than "
        "a network problem. Re-run with --theatre-slug <a real theatre's slug>."
    ),
    RateLimited: (
        "AMC rate-limited this box. This one is our fault, not theirs: wait several "
        "minutes before retrying, and do not tighten the Polling Budget on this box."
    ),
    DiscoveryIncomplete: (
        "This theatre has more showtimes than one discovery query carries, so the "
        "Registry would silently miss some. Raise the page sizes in the discovery "
        "query (or paginate them) before trusting discovery at this theatre."
    ),
    ShapeChanged: (
        "The host answered, but not with what we asked for. Either AMC changed the "
        "payload shape (everything is blind until fetch-core is updated) or this is a "
        "challenge/interstitial page."
    ),
}


def default_showtime_id():
    return os.environ.get("AMC_SMOKE_TEST_SHOWTIME_ID", DEFAULT_SHOWTIME_ID)


def default_theatre_slug():
    return os.environ.get("AMC_SMOKE_TEST_THEATRE_SLUG", DEFAULT_THEATRE_SLUG)


def _fail(e, out):
    print(f"FAIL: {e}", file=out)
    remedy = REMEDIES.get(type(e))
    if remedy:
        print(f"      {remedy}", file=out)
    return 1


def _smoke_seat_page(showtime_id, session, out):
    print(f"GET {seat_page_url(showtime_id)}", file=out)
    try:
        page = fetch_seat_page(showtime_id, session=session)
    except FetchError as e:
        return _fail(e, out)
    print(
        f"PASS: {page.movie_name} - {page.format_name} ({page.format_code}) "
        f"at {page.theatre_name}, {page.starts_at_utc:%Y-%m-%d %H:%M} UTC",
        file=out,
    )
    print(
        f"      {len(page.seats)} seats in the layout, "
        f"{len(page.bookable_seats)} bookable right now",
        file=out,
    )
    return 0


def _smoke_graphql(theatre_slug, graphql_session, out):
    print(f"POST {GRAPHQL_URL} (curl_cffi discovery at {theatre_slug})", file=out)
    try:
        rows = discover_showtimes(
            theatre_slug, business_date=date.today(), session=graphql_session
        )
    except FetchError as e:
        return _fail(e, out)
    where = rows[0].theatre_name if rows else theatre_slug
    print(f"PASS: {len(rows)} showtimes discovered today at {where}", file=out)
    return 0


def smoke_test(showtime_id, theatre_slug, session=None, graphql_session=None, out=None):
    """Probe both AMC surfaces. Returns a process exit code.

    Both probes run even when the first fails — the surfaces fail independently
    (ADR-0005), and an operator wants the whole picture from one invocation.
    """
    out = out or sys.stdout
    seat = _smoke_seat_page(showtime_id, session, out)
    graphql = _smoke_graphql(theatre_slug, graphql_session, out)
    return seat or graphql


def build_parser():
    parser = argparse.ArgumentParser(prog="amc-watch", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    smoke = sub.add_parser(
        "smoke-test",
        help="probe a known Seat Page and the GraphQL host; run this first on any new box",
    )
    smoke.add_argument(
        "--showtime-id",
        default=None,
        help=f"showtime to probe (default: {default_showtime_id()})",
    )
    smoke.add_argument(
        "--theatre-slug",
        default=None,
        help=f"theatre to probe discovery at (default: {default_theatre_slug()})",
    )
    return parser


def main(argv=None, session=None, graphql_session=None):
    args = build_parser().parse_args(argv)
    if args.command == "smoke-test":
        return smoke_test(
            args.showtime_id or default_showtime_id(),
            args.theatre_slug or default_theatre_slug(),
            session=session,
            graphql_session=graphql_session,
        )
    return 2  # pragma: no cover - argparse rejects unknown commands first


if __name__ == "__main__":
    sys.exit(main())
