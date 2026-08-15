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

from .errors import ShapeChanged
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
        raise ShapeChanged(f"{what}: object did not decode ({e})") from e
    if not isinstance(obj, dict):
        raise ShapeChanged(f"{what}: did not decode to an object")
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
    raise ShapeChanged(f"{what}: no enclosing object before anchor")


def extract_layout(text):
    """Pull the seatingLayout object out of an unescaped payload.

    Anchors on the key and decodes its *value*, exactly as the proven parser did.
    """
    m = _LAYOUT_RE.search(text)
    if not m:
        raise ShapeChanged("seat layout: seatingLayout not found in payload")
    at = text.find("{", m.end())
    if at == -1:
        raise ShapeChanged("seat layout: seatingLayout has no object value")
    layout = _decode_object_at(text, at, "seat layout")
    if "seats" not in layout:
        raise ShapeChanged("seat layout: seatingLayout has no seats")
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
        raise ShapeChanged("seat layout: no nameable seats in seatingLayout")
    return tuple(seats)


def _first_edge_node(obj, key):
    edges = (obj.get(key) or {}).get("edges") or []
    return (edges[0].get("node") or {}) if edges else {}


# AMC files every showtime attribute under one of its own groups — Format(3),
# Features(4), Amenities(2), Accessibility(1) — which is how a Format is told apart from
# a recliner or a closed-caption marker *without* hardcoding any format code (confirmed
# by introspection + live sample, 2026-08-14). Matched on id or name so a rename of
# either one alone does not blind us.
FORMAT_ATTRIBUTE_GROUP_ID = 3
FORMAT_ATTRIBUTE_GROUP_NAME = "Format"

# A showtime AMC files under no Format attribute at all — an ordinary screening with no
# premium presentation. Distinct from "we could not find any format information", which
# is a shape change.
NO_FORMAT = {"code": "", "name": ""}


def _is_format_attribute(node):
    return any(
        (group or {}).get("id") == FORMAT_ATTRIBUTE_GROUP_ID
        or (group or {}).get("name") == FORMAT_ATTRIBUTE_GROUP_NAME
        for group in node.get("groups") or []
    )


def format_attributes(obj):
    """A showtime's Format-group attributes, most specific first.

    AMC's `sort` orders them by specificity within the group (imax70mm 8 < imax 11 <
    70mm 23), so the first entry is the format to record.
    """
    nodes = [
        node
        for edge in (obj.get("attributes") or {}).get("edges") or []
        if _is_format_attribute(node := edge.get("node") or {})
    ]
    return sorted(nodes, key=lambda n: n.get("sort") if n.get("sort") is not None else 10**6)


def _format_of(obj):
    """A showtime object's Format node — {code, name}.

    The same idea arrives in three shapes (all observed 2026-08-14): the RSC payload
    embeds `format` as a Relay connection (edges/node); the discovery schema types it
    as ShowtimeMovieFormat with a plain `attributes` list; and live GraphQL answers
    `format: null` with the identity riding the showtime's own AttributeConnection.

    In that third shape the connection is a *mixed* bag — Features, Amenities and
    Accessibility attributes sit alongside the formats, and it is ordered by AMC's
    global `sort`, so the first entry is frequently not a format at all (an ordinary
    2D showtime leads with `reservedseating`). Only Format-group members are eligible.
    Returns NO_FORMAT when AMC listed attributes but none were formats; returns {} when
    there was no format information to read at all, which the caller reports as a shape
    change.
    """
    container = obj.get("format") or {}
    if "edges" in container:
        return _first_edge_node(obj, "format")
    attributes = container.get("attributes") or []
    if attributes:
        return attributes[0]
    if "attributes" not in obj:
        return {}
    formats = format_attributes(obj)
    return formats[0] if formats else NO_FORMAT


def parse_starts_at(raw, what):
    """AMC's `showDateTimeUtc` ISO string → an aware datetime, or ShapeChanged."""
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except (AttributeError, ValueError) as e:
        raise ShapeChanged(f"{what}: unreadable showDateTimeUtc {raw!r}") from e


def parse_int(value, what, showtime_id=None):
    """AMC's numeric IDs → int, or ShapeChanged.

    A schema change to a string- or float-formatted ID passes the callers' `is None`
    missing-field checks and would otherwise surface as a bare ValueError, outside the
    error taxonomy every caller catches on.
    """
    try:
        return int(value)
    except (TypeError, ValueError) as e:
        raise ShapeChanged(f"{what}: unreadable integer {value!r}", showtime_id) from e


def parse_showtime(text):
    """Pull Showtime/Format/movie/theatre metadata out of an unescaped payload."""
    at = text.find(_SHOWTIME_KEY)
    if at == -1:
        raise ShapeChanged("showtime metadata: showDateTimeUtc not found")
    start = _enclosing_object_start(text, at, "showtime metadata")
    return showtime_fields(_decode_object_at(text, start, "showtime metadata"))


def showtime_fields(obj):
    """Reduce a showtime object to the SeatPage metadata fields.

    The RSC payload embeds the very object the GraphQL `viewer.showtime` query returns
    (the Next.js server ran that query for us), so this extraction is shared by both
    backends — one definition of what a SeatPage needs.
    """
    fmt = _format_of(obj)
    movie = obj.get("movie") or {}
    theatre = obj.get("theatre") or {}
    starts_at_utc = parse_starts_at(obj.get("showDateTimeUtc"), "showtime metadata")
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
        raise ShapeChanged(f"showtime metadata: missing {', '.join(missing)}")
    return {
        "showtime_id": parse_int(obj["showtimeId"], "showtime metadata: showtimeId"),
        "movie_id": parse_int(movie["movieId"], "showtime metadata: movie.movieId"),
        "movie_name": movie.get("name") or "",
        "theatre_id": parse_int(theatre["theatreId"], "showtime metadata: theatre.theatreId"),
        "theatre_name": theatre.get("name") or "",
        "format_code": fmt["code"],
        "format_name": fmt.get("name") or "",
        "starts_at_utc": starts_at_utc,
    }


def parse_seat_page(html):
    """Parse a raw Seat Page response body into a SeatPage.

    Raises ShapeChanged if the payload no longer looks like a Seat Page — never
    returns a SeatPage with no seats to mean that.
    """
    text = unescape_payload(html)
    return SeatPage(seats=parse_seats(extract_layout(text)), **parse_showtime(text))
