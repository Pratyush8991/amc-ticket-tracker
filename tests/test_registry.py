"""The Registry: Contribution, enrichment, and querying what is covered.

The pass under test here is the one the poller will call in #4, so it is driven directly
and synchronously — no loops, no sleeps. Exactly one thing is faked: `session.get`. The
recorded Seat Page is parsed for real, which is what makes "no human supplies Showtime
metadata" (ADR-0001) a claim these tests can actually check.
"""

from datetime import datetime, timezone

from amc_watch.registry import contribute, enrich_pending, list_showtimes


def test_a_contributed_bare_id_fills_itself_in_from_its_seat_page(db_session, as_recorded):
    """The whole point of the Registry: a bare number becomes a described Showtime."""
    contribute(db_session, ["144696966"])

    enrich_pending(db_session, session=as_recorded)

    (showtime,) = list_showtimes(db_session)
    assert showtime.movie_name == "The Odyssey"
    assert showtime.theatre_name == "AMC Metreon 16"
    assert (showtime.format_code, showtime.format_name) == ("imax70mm", "IMAX 70MM")
    assert showtime.starts_at_utc == datetime(2026, 8, 9, 17, 0, tzinfo=timezone.utc)
    assert showtime.layout is not None
