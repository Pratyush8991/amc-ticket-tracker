"""Walk GraphQL JSON payloads into the shared fetch-core models.

Deliberately mirrors the RSC parser's contract: a payload that no longer carries what we
queried raises ShapeChanged — never an empty result — and the seat flattening plus the
SeatPage metadata extraction are literally shared with the RSC side (`parse_seats`,
`showtime_fields`), so both backends stay one value object by construction.
"""

from ..errors import ShapeChanged
from ..model import SeatPage
from ..parse import parse_seats, showtime_fields


def _viewer(payload, what):
    data = payload.get("data") if isinstance(payload, dict) else None
    viewer = data.get("viewer") if isinstance(data, dict) else None
    if not isinstance(viewer, dict):
        raise ShapeChanged(f"{what}: GraphQL response has no viewer")
    return viewer


def parse_seat_response(payload, showtime_id):
    """Reduce a seat-query response to a SeatPage."""
    node = _viewer(payload, "graphql seat read").get("showtime")
    if not isinstance(node, dict):
        raise ShapeChanged("graphql seat read: response has no showtime", showtime_id)
    layout = node.get("seatingLayout")
    if not isinstance(layout, dict) or "seats" not in layout:
        raise ShapeChanged("graphql seat read: showtime has no seatingLayout", showtime_id)
    return SeatPage(seats=parse_seats(layout), **showtime_fields(node))
