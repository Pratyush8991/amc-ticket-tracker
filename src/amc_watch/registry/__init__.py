"""Contribution, enrichment and Showtime storage — the shared Registry.

Two steps, deliberately separate. Contribution is pure storage: it takes bare showtime IDs
and writes rows, touching the network never. Enrichment is the pass that spends a Seat
Page fetch to fill one of those rows in — which is why it is a single synchronous pass
the poller can call later (ADR-0002), not a loop.
"""

from datetime import datetime, timezone

from sqlalchemy import select

from ..db import Showtime
from ..fetch_core import fetch_seat_page


def contribute(db, given):
    """Store bare showtime IDs as Registry rows, unenriched."""
    for token in given:
        showtime_id = int(token)
        if db.get(Showtime, showtime_id) is None:
            db.add(Showtime(showtime_id=showtime_id))
    db.commit()


def enrich_pending(db, session=None):
    """Fill in every row that has never been enriched, one Seat Page fetch each."""
    pending = db.scalars(select(Showtime).where(Showtime.enriched_at.is_(None))).all()
    for showtime in pending:
        page = fetch_seat_page(showtime.showtime_id, session=session)
        showtime.movie_id = page.movie_id
        showtime.movie_name = page.movie_name
        showtime.theatre_id = page.theatre_id
        showtime.theatre_name = page.theatre_name
        showtime.format_code = page.format_code
        showtime.format_name = page.format_name
        showtime.starts_at_utc = page.starts_at_utc
        showtime.layout = _layout_of(page)
        showtime.enriched_at = datetime.now(timezone.utc)
        db.commit()


def _layout_of(page):
    """The seat grid, kept so the seat picker can draw this house without a fetch."""
    return {
        "seats": [
            {
                "name": seat.name,
                "row": seat.grid_row,
                "column": seat.grid_col,
                "available": seat.available,
                "type": seat.seat_type,
            }
            for seat in page.seats
        ]
    }


def list_showtimes(db):
    """The Registry as a user browses it."""
    return db.scalars(select(Showtime).order_by(Showtime.showtime_id)).all()
