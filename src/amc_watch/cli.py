"""Operator command line.

    amc-watch smoke-test [--showtime-id ID]

The smoke test is the first act on any new box (ADR-0004): one GET of a known Seat Page,
pass or fail with the reason. Every proof that Seat Pages accept plain HTTP was taken
from a residential IP, so until this passes on a given machine, nothing else built on it
can be trusted to work.
"""

import argparse
import os
import sys

from .fetch_core import (
    AccessBlocked,
    QueueWalled,
    RateLimited,
    SeatPageError,
    SeatPageShapeChanged,
    ShowtimeNotFound,
    fetch_seat_page,
    seat_page_url,
)

# A Seat Page known to exist. Showtimes pass, so this rots by design — hence
# --showtime-id and AMC_SMOKE_TEST_SHOWTIME_ID. A ShowtimeNotFound from the default is a
# stale constant, not a blocked box, and the failure text says so.
DEFAULT_SHOWTIME_ID = "144696969"

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
    RateLimited: (
        "AMC rate-limited this box. This one is our fault, not theirs: wait several "
        "minutes before retrying, and do not tighten the Polling Budget on this box."
    ),
    SeatPageShapeChanged: (
        "The page loaded but carried no seatingLayout. Either AMC changed the payload "
        "shape (everything is blind until the parser is updated) or this is a "
        "challenge/interstitial page."
    ),
}


def default_showtime_id():
    return os.environ.get("AMC_SMOKE_TEST_SHOWTIME_ID", DEFAULT_SHOWTIME_ID)


def smoke_test(showtime_id, session=None, out=None):
    """One GET of a known Seat Page. Returns a process exit code."""
    out = out or sys.stdout
    print(f"GET {seat_page_url(showtime_id)}", file=out)

    try:
        page = fetch_seat_page(showtime_id, session=session)
    except SeatPageError as e:
        print(f"FAIL: {e}", file=out)
        remedy = REMEDIES.get(type(e))
        if remedy:
            print(f"      {remedy}", file=out)
        return 1

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


def build_parser():
    parser = argparse.ArgumentParser(prog="amc-watch", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    smoke = sub.add_parser(
        "smoke-test",
        help="one GET of a known Seat Page; run this first on any new box",
    )
    smoke.add_argument(
        "--showtime-id",
        default=None,
        help=f"showtime to probe (default: {default_showtime_id()})",
    )
    return parser


def main(argv=None, session=None):
    args = build_parser().parse_args(argv)
    if args.command == "smoke-test":
        return smoke_test(args.showtime_id or default_showtime_id(), session=session)
    return 2  # pragma: no cover - argparse rejects unknown commands first


if __name__ == "__main__":
    sys.exit(main())
