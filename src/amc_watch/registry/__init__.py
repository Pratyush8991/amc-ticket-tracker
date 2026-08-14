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
from sqlalchemy.dialects.postgresql import insert

from ..db import Showtime
from ..fetch_core import (
    AccessBlocked,
    QueueWalled,
    RateLimited,
    SeatPageError,
    SeatPageShapeChanged,
    ShowtimeNotFound,
    fetch_seat_page,
)

# `[0-9]`, not `\d` — Python's `\d` and `str.isdigit()` both accept non-ASCII digits, and
# `int("١٤٤")` quietly returns 144, which would contribute a showtime nobody typed.
_DIGITS_RE = re.compile(r"[0-9]+")
_URL_ID_RE = re.compile(r"/showtimes/([0-9]+)")

# What the Seat Page refused us, in a word. Only `dead` is a verdict about the Showtime
# itself; the rest are verdicts about this attempt, and the row keeps its turn. Collapsing
# them into one word would undo the whole point of the error taxonomy (see errors.py):
# a changed payload and a queue wall need opposite reactions from an operator.
FAILURE_STATUS = {
    ShowtimeNotFound: "dead",
    QueueWalled: "queued",
    AccessBlocked: "blocked",
    RateLimited: "throttled",
    SeatPageShapeChanged: "unreadable",
}
UNKNOWN_FAILURE_STATUS = "unreachable"

# How much of a driver's complaint we keep. `last_error` is a bounded column, and Postgres
# raises rather than truncating, so an over-long message would abort the whole pass.
MAX_ERROR_LENGTH = 500


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
    if _DIGITS_RE.fullmatch(token):
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
        # Let the primary key settle new-vs-duplicate, rather than looking first and
        # inserting second: the Registry is shared, and two friends harvesting the same
        # AMC page at the same moment must collide harmlessly instead of one of them
        # losing their whole batch to an IntegrityError.
        claimed = db.scalar(
            insert(Showtime)
            .values(showtime_id=showtime_id)
            .on_conflict_do_nothing(index_elements=["showtime_id"])
            .returning(Showtime.showtime_id)
        )
        if claimed is not None:
            outcomes.append(Outcome(given=str(token), status="new", showtime_id=showtime_id))
            continue
        known = db.get(Showtime, showtime_id)
        if known is not None and known.dead_at is not None:
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


def enrich_pending(db, session=None, showtime_ids=None, limit=None):
    """Fill in rows that have never been enriched, one Seat Page fetch each.

    One synchronous pass, no loop and no sleep — this is the entry point the poller
    drives later (ADR-0002). Returns one Outcome per row it attempted, so a failure is
    reported to whoever asked rather than logged into the void.

    `showtime_ids` narrows the pass to specific rows. Without it the pass covers the whole
    shared Registry, which is right for the poller and wrong for a person who just typed
    two IDs — every pending row anyone ever contributed would be fetched back-to-back.
    """
    outcomes = []
    for showtime in _pending(db, showtime_ids=showtime_ids, limit=limit):
        try:
            page = fetch_seat_page(showtime.showtime_id, session=session)
        except SeatPageError as e:
            # Only "no such showtime" is a verdict about the Showtime; every other wall is
            # a verdict about this attempt, so the row keeps its turn — but it keeps it
            # under its own name, because a changed payload and a queue wall call for
            # opposite reactions from whoever is reading.
            outcomes.append(
                _failure(db, showtime, FAILURE_STATUS.get(type(e), UNKNOWN_FAILURE_STATUS), e)
            )
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


def _pending(db, showtime_ids=None, limit=None):
    """Rows still owed a first Seat Page fetch. Dead IDs are not owed one.

    Rows are locked and already-locked ones skipped, so two passes running at once — the
    poller on its timer and an operator at a keyboard — split the work instead of both
    fetching the same Seat Pages. With no broker (ADR-0002) this table is the only place
    they can agree, and the thing being double-spent is the Polling Budget.
    """
    query = (
        select(Showtime)
        .where(Showtime.enriched_at.is_(None), Showtime.dead_at.is_(None))
        .order_by(Showtime.showtime_id)
        .with_for_update(skip_locked=True)
    )
    if showtime_ids is not None:
        query = query.where(Showtime.showtime_id.in_(list(showtime_ids)))
    if limit is not None:
        query = query.limit(limit)
    return db.scalars(query).all()


def _failure(db, showtime, status, error, terminal_status="dead"):
    """Record why a fetch failed so the reason outlives this pass."""
    # Bounded, because the column is: Postgres raises on over-long values rather than
    # truncating, and a driver's complaint about TLS can run to several hundred characters.
    showtime.last_error = str(error)[:MAX_ERROR_LENGTH]
    if status == terminal_status:
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


def _contains(column, text):
    """A case-insensitive substring match on literal text.

    `%` and `_` are escaped rather than honoured: someone filtering for `spider_man` means
    an underscore, not "any character", and would have no way to explain why Spider-Man
    came back.
    """
    escaped = text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return column.ilike(f"%{escaped}%", escape="\\")


def list_showtimes(db, movie=None, theatre=None, format=None, enriched_only=False):
    """The Registry as a user browses it, narrowed the way a Watch selector narrows.

    Filters are case-insensitive substrings so that "doomsday" finds Avengers Doomsday and
    "metreon" finds AMC Metreon 16 — nobody should have to retype AMC's exact title. A
    format matches on either its code or its printed name, since users know it as
    "IMAX 70MM" while the Seat Page calls it `imax70mm`.

    `enriched_only` is what a Watch selector needs: only enriched Showtimes can be covered
    or polled. A person browsing wants the opposite — pending and dead rows are exactly
    what they are checking on — so the default shows everything.
    """
    query = select(Showtime).order_by(Showtime.showtime_id)
    if enriched_only:
        query = query.where(Showtime.enriched_at.is_not(None), Showtime.dead_at.is_(None))
    if movie:
        query = query.where(_contains(Showtime.movie_name, movie))
    if theatre:
        query = query.where(_contains(Showtime.theatre_name, theatre))
    if format:
        query = query.where(
            _contains(Showtime.format_code, format) | _contains(Showtime.format_name, format)
        )
    return db.scalars(query).all()
