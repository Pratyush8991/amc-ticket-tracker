"""Contribution, enrichment and Showtime storage — the shared Registry.

Two steps, deliberately separate. Contribution is pure storage: it takes bare showtime IDs
and writes rows, touching the network never. Enrichment is the pass that spends a Seat
Page fetch to fill one of those rows in — which is why it is a single synchronous pass
the poller can call later (ADR-0002), not a loop.
"""

import re
from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy import select

from ..db import Showtime
from ..fetch_core import SeatPageError, ShowtimeNotFound, fetch_seat_page

_URL_ID_RE = re.compile(r"/showtimes/(\d+)")


@dataclass(frozen=True)
class Outcome:
    """What became of one contributed or enriched showtime ID.

    Every ID a user hands us gets one of these back. That is the whole guarantee behind
    "typos don't vanish silently": a Contribution never reports fewer results than it was
    given, so there is always something to print next to the ID that went wrong.
    """

    given: str
    status: str
    showtime_id: int | None = None
    detail: str = ""


def showtime_id_from(token):
    """Read a showtime ID out of whatever a user pasted.

    A bare number is the canonical Contribution, but what is actually on someone's
    clipboard after they browse AMC as a human is the Seat Page URL — so the ID is taken
    from the `/showtimes/<id>/` segment rather than asking anyone to retype it.
    """
    token = str(token).strip()
    if token.isdigit():
        return int(token)
    m = _URL_ID_RE.search(token)
    return int(m.group(1)) if m else None


def contribute(db, given):
    """Store bare showtime IDs as Registry rows, unenriched. One Outcome per ID."""
    outcomes = []
    for token in given:
        showtime_id = showtime_id_from(token)
        if showtime_id is None:
            outcomes.append(
                Outcome(
                    given=str(token),
                    status="invalid",
                    detail="not a showtime ID or Seat Page URL",
                )
            )
            continue
        known = db.get(Showtime, showtime_id)
        if known is None:
            db.add(Showtime(showtime_id=showtime_id))
            outcomes.append(Outcome(given=str(token), status="new", showtime_id=showtime_id))
        elif known.dead_at is not None:
            # Contributing a typo twice must not look like contributing a good ID twice.
            outcomes.append(
                Outcome(
                    given=str(token),
                    status="dead",
                    showtime_id=showtime_id,
                    detail=f"already known: {known.last_error}",
                )
            )
        else:
            outcomes.append(Outcome(given=str(token), status="duplicate", showtime_id=showtime_id))
    db.commit()
    return outcomes


def enrich_pending(db, session=None):
    """Fill in every row that has never been enriched, one Seat Page fetch each.

    One synchronous pass, no loop and no sleep — this is the entry point the poller
    drives later (ADR-0002). Returns one Outcome per row it attempted, so a failure is
    reported to whoever asked rather than logged into the void.
    """
    outcomes = []
    for showtime in _pending(db):
        try:
            page = fetch_seat_page(showtime.showtime_id, session=session)
        except ShowtimeNotFound as e:
            outcomes.append(_failure(db, showtime, "dead", e, dead=True))
            continue
        except SeatPageError as e:
            # A wall, a 403, a shape change: we never got a trustworthy answer, so the
            # row keeps its turn. Only AMC saying "no such showtime" is final.
            outcomes.append(_failure(db, showtime, "queued", e))
            continue
        _fill_in(showtime, page)
        db.commit()
        outcomes.append(
            Outcome(
                given=str(showtime.showtime_id),
                status="enriched",
                showtime_id=showtime.showtime_id,
                detail=f"{page.movie_name} / {page.format_name} ({page.format_code})",
            )
        )
    return outcomes


def _pending(db):
    """Rows still owed a first Seat Page fetch. Dead IDs are not owed one."""
    return db.scalars(
        select(Showtime)
        .where(Showtime.enriched_at.is_(None), Showtime.dead_at.is_(None))
        .order_by(Showtime.showtime_id)
    ).all()


def _failure(db, showtime, status, error, dead=False):
    """Record why a fetch failed so the reason outlives this pass."""
    showtime.last_error = str(error)
    if dead:
        showtime.dead_at = datetime.now(timezone.utc)
    db.commit()
    return Outcome(
        given=str(showtime.showtime_id),
        status=status,
        showtime_id=showtime.showtime_id,
        detail=str(error),
    )


def _fill_in(showtime, page):
    """Copy a Seat Page onto its Registry row. Every value here came from AMC."""
    showtime.movie_id = page.movie_id
    showtime.movie_name = page.movie_name
    showtime.theatre_id = page.theatre_id
    showtime.theatre_name = page.theatre_name
    # Stored exactly as reported. InfinityVision's code is unknown until the first
    # Doomsday Contribution reveals it, so nothing here may be normalised or mapped.
    showtime.format_code = page.format_code
    showtime.format_name = page.format_name
    showtime.starts_at_utc = page.starts_at_utc
    showtime.layout = _layout_of(page)
    showtime.enriched_at = datetime.now(timezone.utc)
    showtime.last_error = None


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
