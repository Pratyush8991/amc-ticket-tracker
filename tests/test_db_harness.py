"""The test harness itself, and the baseline schema it applies.

If these fail, nothing else in the suite can be trusted: every later slice assumes a
migrated Postgres it can write domain rows into.
"""

from datetime import datetime, timezone

from sqlalchemy import inspect, select

from amc_watch.db import Showtime
from amc_watch.fetch_core import fetch_seat_page


def test_the_baseline_migration_applies_to_a_fresh_database(migrated_database):
    """A fresh box runs `alembic upgrade head` and gets the Registry."""
    from sqlalchemy import create_engine

    engine = create_engine(migrated_database)
    try:
        tables = set(inspect(engine).get_table_names())
    finally:
        engine.dispose()

    assert "showtimes" in tables
    assert "alembic_version" in tables


def test_a_showtime_survives_a_round_trip(db_session):
    """Timezone-aware start times and the JSONB layout come back as they went in."""
    db_session.add(
        Showtime(
            showtime_id=144696966,
            movie_id=76238,
            movie_name="The Odyssey",
            theatre_id=2325,
            theatre_name="AMC Metreon 16",
            format_code="imax70mm",
            format_name="IMAX 70MM",
            starts_at_utc=datetime(2026, 8, 9, 17, 0, tzinfo=timezone.utc),
            layout={"columns": 34, "rows": 13},
        )
    )
    db_session.flush()
    db_session.expunge_all()

    stored = db_session.scalar(select(Showtime).where(Showtime.showtime_id == 144696966))
    assert stored.movie_name == "The Odyssey"
    assert stored.format_code == "imax70mm"
    assert stored.starts_at_utc == datetime(2026, 8, 9, 17, 0, tzinfo=timezone.utc)
    assert stored.layout == {"columns": 34, "rows": 13}
    assert stored.first_seen_at is not None


def test_a_parsed_seat_page_fits_the_registry_row(db_session, as_recorded):
    """The enrichment path end to end: bare ID -> Seat Page -> a persisted Showtime.

    This is what makes Contribution zero-typing — every column below came from the page.
    """
    page = fetch_seat_page(144696966, session=as_recorded)

    db_session.add(
        Showtime(
            showtime_id=page.showtime_id,
            movie_id=page.movie_id,
            movie_name=page.movie_name,
            theatre_id=page.theatre_id,
            theatre_name=page.theatre_name,
            format_code=page.format_code,
            format_name=page.format_name,
            starts_at_utc=page.starts_at_utc,
        )
    )
    db_session.flush()
    db_session.expunge_all()

    stored = db_session.scalar(select(Showtime).where(Showtime.showtime_id == 144696966))
    assert (stored.movie_name, stored.theatre_name) == ("The Odyssey", "AMC Metreon 16")
    assert stored.format_code == "imax70mm"
