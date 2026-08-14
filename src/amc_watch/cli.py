"""Operator command line.

    amc-watch smoke-test [--showtime-id ID]
    amc-watch contribute <id-or-seat-page-url>... [--enrich]

The smoke test is the first act on any new box (ADR-0004): one GET of a known Seat Page,
pass or fail with the reason. Every proof that Seat Pages accept plain HTTP was taken
from a residential IP, so until this passes on a given machine, nothing else built on it
can be trusted to work.

`contribute` is how showtime IDs reach the Registry until the web UI exists (#9). It
touches no network — enrichment is the separate pass that spends the Seat Page fetch.
"""

import argparse
import os
import sys

from sqlalchemy.engine import make_url
from sqlalchemy.exc import ArgumentError, OperationalError, ProgrammingError, SQLAlchemyError

from . import registry
from .db import create_engine_from_env, database_url, session_factory
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
#
# Note the ID waves are not contiguous with each other: Aug 9 was 1446969xx and Aug 15 is
# 1453774xx. Do not try to guess a fresh ID by probing outward from a stale one — that is
# the range-probing ADR-0001 rejected, and it would not even work.
DEFAULT_SHOWTIME_ID = "145377422"  # The Odyssey, IMAX 70mm, Metreon 16, Sat 2026-08-15

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


# An ID that reached the Registry as intended. `duplicate` counts: another friend having
# already contributed it is the system working, not a problem. Everything else — every
# wall AMC put up, every token we could not read — is a reason to exit non-zero, and
# listing the good outcomes rather than the bad ones means a new failure mode cannot
# quietly join the set that reports success.
PLACED = frozenset({"new", "duplicate", "enriched"})


def exit_code_for(outcomes):
    """Non-zero if any ID went unplaced — the only part of a report a script can read."""
    return 1 if any(o.status not in PLACED for o in outcomes) else 0


def report(outcomes, out):
    """Print one line per showtime ID, whatever became of it.

    Every ID gets a line, including the ones that failed — a Contribution that swallowed
    a typo would be worse than one that rejected it loudly.
    """
    for outcome in outcomes:
        # A pasted Seat Page URL is reported as the showtime it resolved to; only a token
        # we could not read at all is echoed back verbatim, so the user can spot the typo.
        label = outcome.showtime_id or outcome.given
        print(f"  {label:<12} {outcome.status:<10} {outcome.detail}".rstrip(), file=out)


def contribute_command(given, enrich=False, db=None, session=None, out=None):
    """Store contributed IDs, optionally enriching them in the same breath."""
    out = out or sys.stdout
    outcomes = registry.contribute(db, given)
    report(outcomes, out)
    if enrich:
        # Only the IDs this person just handed us. The Registry is shared, so an
        # unscoped pass here would spend one fetch on every pending row in it —
        # hundreds, back to back, against the one endpoint the system depends on.
        just_contributed = [o.showtime_id for o in outcomes if o.showtime_id is not None]
        outcomes = outcomes + enrich_command(
            db=db, session=session, out=out, showtime_ids=just_contributed
        )
    return outcomes


def enrich_command(db=None, session=None, out=None, showtime_ids=None):
    """One enrichment pass over everything still owed a Seat Page fetch."""
    out = out or sys.stdout
    outcomes = registry.enrich_pending(db, session=session, showtime_ids=showtime_ids)
    if not outcomes:
        # An operator who sees nothing must be able to tell "all caught up" from "broke".
        print("  nothing pending", file=out)
    report(outcomes, out)
    return outcomes


def registry_command(movie=None, theatre=None, format=None, db=None, out=None):
    """Print the Registry, narrowed the way a Watch selector narrows it."""
    out = out or sys.stdout
    showtimes = registry.list_showtimes(db, movie=movie, theatre=theatre, format=format)
    if not showtimes:
        print("  nothing in the Registry matches", file=out)
    for showtime in showtimes:
        print(f"  {showtime.showtime_id:<12} {_describe(showtime)}", file=out)
    return showtimes


def _describe(showtime):
    """One line about a Showtime, whether or not it has been enriched yet."""
    # Death is checked first because it can strike long after Enrichment (CONTEXT.md), and
    # a row still reading "enriched" would have someone watching a screening AMC pulled.
    if showtime.dead_at is not None:
        return f"{'dead':<10} {showtime.last_error or 'AMC says it does not exist'}"
    if showtime.enriched_at is None:
        return f"{'pending':<10} {showtime.last_error or 'awaiting its Seat Page'}"
    return (
        f"{'enriched':<10} {showtime.movie_name} — {showtime.format_name} "
        f"({showtime.format_code}) at {showtime.theatre_name}, "
        f"{showtime.starts_at_utc:%Y-%m-%d %H:%M} UTC"
    )


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

    contribute = sub.add_parser(
        "contribute",
        help="add showtime IDs (or pasted Seat Page URLs) to the Registry",
    )
    contribute.add_argument("given", nargs="+", metavar="ID-OR-URL")
    contribute.add_argument(
        "--enrich",
        action="store_true",
        help="also run the enrichment pass, so the rows fill themselves in now",
    )

    sub.add_parser(
        "enrich",
        help="fill in every Registry row still owed a Seat Page fetch",
    )

    listing = sub.add_parser("registry", help="show what the Registry already covers")
    # The three axes a Watch selector matches on; all case-insensitive substrings.
    listing.add_argument("--movie", default=None)
    listing.add_argument("--theatre", default=None)
    listing.add_argument("--format", default=None)
    return parser


def _with_db(db, run):
    """Run against the caller's session, or open one for the length of the command."""
    if db is not None:
        return run(db)
    engine = create_engine_from_env()
    try:
        with session_factory(engine)() as opened:
            return run(opened)
    finally:
        engine.dispose()


def safe_database_url():
    """The configured database with its password masked.

    Printed at the exact moment someone is about to paste our output into a bug report or
    a chat, so the credentials must not be in it.
    """
    try:
        return make_url(database_url()).render_as_string(hide_password=True)
    except ArgumentError:
        # An unparseable URL is itself the likely fault, but it may embed a password.
        return "<unreadable DATABASE_URL>"


def report_database_failure(error, out=None):
    """Say which database we could not use and what to do about it.

    The same courtesy the smoke test extends to a blocked box: someone who just SSH'd in
    should get a remedy, not a driver stack trace. Returns a process exit code.
    """
    out = out or sys.stdout
    print(f"FAIL: could not use the Registry database at {safe_database_url()}", file=out)
    print(
        "      Point DATABASE_URL at your Postgres and apply the schema with "
        "`alembic upgrade head`.",
        file=out,
    )
    # The driver's own first line, which is where the actual cause lives.
    print(f"      {str(error).splitlines()[0]}", file=out)
    return 1


def report_database_error(error, out=None):
    """A database error that is not about reachability — so no misleading remedy.

    Telling someone to run `alembic upgrade head` because their showtime ID overflowed a
    bigint sends them to fix the one thing that was never wrong.
    """
    out = out or sys.stdout
    print(f"FAIL: the Registry rejected that: {str(error).splitlines()[0]}", file=out)
    return 1


def main(argv=None, session=None, db=None):
    args = build_parser().parse_args(argv)
    if args.command == "smoke-test":
        return smoke_test(args.showtime_id or default_showtime_id(), session=session)
    try:
        if args.command == "contribute":
            return exit_code_for(
                _with_db(
                    db,
                    lambda opened: contribute_command(
                        args.given, enrich=args.enrich, db=opened, session=session
                    ),
                )
            )
        if args.command == "enrich":
            return exit_code_for(
                _with_db(db, lambda opened: enrich_command(db=opened, session=session))
            )
        if args.command == "registry":
            _with_db(
                db,
                lambda opened: registry_command(
                    movie=args.movie, theatre=args.theatre, format=args.format, db=opened
                ),
            )
            return 0
    except (OperationalError, ProgrammingError, ArgumentError) as e:
        # Unreachable, unmigrated, wrong credentials — all the same to the operator:
        # the Registry is not usable from here, and here is what to check.
        return report_database_failure(e)
    except SQLAlchemyError as e:
        # Reached the database fine; it disliked what we sent. Still no stack trace, but
        # emphatically not the "check DATABASE_URL" advice either.
        return report_database_error(e)
    return 2  # pragma: no cover - argparse rejects unknown commands first


if __name__ == "__main__":
    sys.exit(main())
