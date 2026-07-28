"""Value objects a parsed Seat Page yields.

Deliberately dumb data: fetch-core's job ends at "here is what AMC said". Opening
computation, Seat Criteria matching and Party Size live in `watching` — a Seat here does
not know whether anyone wants it.
"""

from dataclasses import dataclass, field
from datetime import datetime

# AMC's seat type for a seat a normal customer can actually reserve. Wheelchair and
# Companion seats report available=True too, which is why availability alone is not
# bookability (CONTEXT.md, "Bookable").
BOOKABLE_TYPES = frozenset({"CanReserve"})


@dataclass(frozen=True)
class Seat:
    """One seat in an auditorium's grid.

    `grid_row`/`grid_col` are AMC's layout coordinates and are what adjacency is computed
    from later: aisles are NotASeat cells and wheelchair/companion seats occupy their own
    columns, so both break adjacency naturally. `row_letter`/`number` are the *printed*
    name a human reads off the ticket ("N7") and are what Seat Criteria are expressed in.
    """

    name: str
    row_letter: str
    number: int
    grid_row: int
    grid_col: int
    available: bool
    seat_type: str

    @property
    def bookable(self):
        """Available *and* a seat a normal customer may reserve."""
        return self.available and self.seat_type in BOOKABLE_TYPES


@dataclass(frozen=True)
class SeatPage:
    """A Seat Page reduced to the domain: the Showtime it describes, plus its seats.

    Self-describing per ADR-0001 — every field here came from a bare showtime ID, which
    is why no human ever supplies Showtime metadata.
    """

    showtime_id: int
    movie_id: int
    movie_name: str
    theatre_id: int
    theatre_name: str
    format_code: str
    format_name: str
    starts_at_utc: datetime
    seats: tuple = field(default_factory=tuple)

    @property
    def bookable_seats(self):
        return tuple(s for s in self.seats if s.bookable)
