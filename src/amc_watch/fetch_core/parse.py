"""Reduce a Seat Page's Next.js RSC payload to a SeatPage.

The page is server-rendered: its RSC payload is spread across `self.__next_f.push([1,"…"])`
script chunks whose contents are JS string literals, so every quote arrives escaped as \\".
Two objects matter, and each appears exactly once in the unescaped document, which is what
lets us anchor on a key name rather than walk the chunk structure:

  "seatingLayout"   — columns/rows/seats, every seat with grid coords, printed name,
                      availability and type
  "showDateTimeUtc" — inside the showtime object carrying format, movie and theatre

Ported from the proven single-user parser (`amc_watch.seats`), whose unescape-then-
raw_decode approach is kept intact.
"""

import json
import re
from datetime import datetime

from .errors import SeatPageShapeChanged
from .model import Seat, SeatPage

_LAYOUT_RE = re.compile(r'"seatingLayout"\s*:\s*')
_SHOWTIME_KEY = '"showDateTimeUtc"'
_NAME_RE = re.compile(r"^([A-Z]+)(\d+)$")


def unescape_payload(html):
    """Undo the RSC string-literal escaping so the embedded JSON can be decoded.

    Applied to the whole document, which is enough for our two anchors but does mangle
    unrelated inline scripts — so only ever look up keys known to be unique.
    """
    return html.replace('\\"', '"').replace("\\\\", "\\")


def _decode_object_at(text, start, what):
    try:
        obj, _ = json.JSONDecoder().raw_decode(text, start)
    except json.JSONDecodeError as e:
        raise SeatPageShapeChanged(f"{what}: object did not decode ({e})") from e
    if not isinstance(obj, dict):
        raise SeatPageShapeChanged(f"{what}: did not decode to an object")
    return obj


def _enclosing_object_start(text, at, what):
    """Walk back from `at` to the `{` that opens the object containing it.

    Needed because the anchor key sits *inside* the object we want, after sibling keys
    whose own nested objects would fool a plain reverse search for "{".
    """
    depth = 0
    for i in range(at - 1, -1, -1):
        c = text[i]
        if c == "}":
            depth += 1
        elif c == "{":
            if depth == 0:
                return i
            depth -= 1
    raise SeatPageShapeChanged(f"{what}: no enclosing object before anchor")


def extract_layout(text):
    """Pull the seatingLayout object out of an unescaped payload.

    Anchors on the key and decodes its *value*, exactly as the proven parser did.
    """
    m = _LAYOUT_RE.search(text)
    if not m:
        raise SeatPageShapeChanged("seat layout: seatingLayout not found in payload")
    at = text.find("{", m.end())
    if at == -1:
        raise SeatPageShapeChanged("seat layout: seatingLayout has no object value")
    layout = _decode_object_at(text, at, "seat layout")
    if "seats" not in layout:
        raise SeatPageShapeChanged("seat layout: seatingLayout has no seats")
    return layout


def parse_seats(layout):
    """Flatten a seatingLayout to Seats, dropping non-seat grid cells.

    NotASeat cells are aisles and gaps; they are skipped here but their grid columns are
    what make adjacency fall out correctly downstream, so the coordinates are preserved
    as-is rather than renumbered.
    """
    seats = []
    for raw in layout.get("seats", []):
        if raw.get("type") == "NotASeat":
            continue
        m = _NAME_RE.match(raw.get("name") or "")
        if not m:
            continue
        if raw.get("row") is None or raw.get("column") is None:
            continue
        seats.append(
            Seat(
                name=raw["name"],
                row_letter=m.group(1),
                number=int(m.group(2)),
                grid_row=raw["row"],
                grid_col=raw["column"],
                available=bool(raw.get("available")),
                seat_type=raw.get("type"),
            )
        )
    if not seats:
        raise SeatPageShapeChanged("seat layout: no nameable seats in seatingLayout")
    return tuple(seats)


def _first_edge_node(obj, key):
    edges = (obj.get(key) or {}).get("edges") or []
    return (edges[0].get("node") or {}) if edges else {}


def parse_showtime(text):
    """Pull Showtime/Format/movie/theatre metadata out of an unescaped payload."""
    at = text.find(_SHOWTIME_KEY)
    if at == -1:
        raise SeatPageShapeChanged("showtime metadata: showDateTimeUtc not found")
    start = _enclosing_object_start(text, at, "showtime metadata")
    obj = _decode_object_at(text, start, "showtime metadata")
    fmt = _first_edge_node(obj, "format")
    movie = obj.get("movie") or {}
    theatre = obj.get("theatre") or {}
    raw_start = obj.get("showDateTimeUtc")
    try:
        starts_at_utc = datetime.fromisoformat(raw_start.replace("Z", "+00:00"))
    except (AttributeError, ValueError) as e:
        raise SeatPageShapeChanged(
            f"showtime metadata: unreadable showDateTimeUtc {raw_start!r}"
        ) from e
    missing = [
        k
        for k, v in {
            "showtimeId": obj.get("showtimeId"),
            "movie.movieId": movie.get("movieId"),
            "theatre.theatreId": theatre.get("theatreId"),
            # Format codes are never hardcoded — InfinityVision's is unknown until the
            # first Doomsday contribution lands (parent #1, "Registry enrichment").
            "format.code": fmt.get("code"),
        }.items()
        if v is None
    ]
    if missing:
        raise SeatPageShapeChanged(f"showtime metadata: missing {', '.join(missing)}")
    return {
        "showtime_id": int(obj["showtimeId"]),
        "movie_id": int(movie["movieId"]),
        "movie_name": movie.get("name") or "",
        "theatre_id": int(theatre["theatreId"]),
        "theatre_name": theatre.get("name") or "",
        "format_code": fmt["code"],
        "format_name": fmt.get("name") or "",
        "starts_at_utc": starts_at_utc,
    }


def parse_seat_page(html):
    """Parse a raw Seat Page response body into a SeatPage.

    Raises SeatPageShapeChanged if the payload no longer looks like a Seat Page — never
    returns a SeatPage with no seats to mean that.
    """
    text = unescape_payload(html)
    return SeatPage(seats=parse_seats(extract_layout(text)), **parse_showtime(text))
