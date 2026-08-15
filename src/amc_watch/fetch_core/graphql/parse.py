"""Walk GraphQL JSON payloads into the shared fetch-core models.

Deliberately mirrors the RSC parser's contract: a payload that no longer carries what we
queried raises ShapeChanged — never an empty result — and the seat flattening plus the
SeatPage metadata extraction are literally shared with the RSC side (`parse_seats`,
`showtime_fields`), so both backends stay one value object by construction.
"""

from ..errors import (
    DiscoveryIncomplete,
    ShapeChanged,
    ShowtimeNotFound,
    TheatreNotFound,
)
from ..model import DiscoveredShowtime, SeatPage, Theatre
from ..parse import _format_of, parse_int, parse_seats, parse_starts_at, showtime_fields


def _viewer(payload, what):
    data = payload.get("data") if isinstance(payload, dict) else None
    viewer = data.get("viewer") if isinstance(data, dict) else None
    if not isinstance(viewer, dict):
        raise ShapeChanged(f"{what}: GraphQL response has no viewer")
    return viewer


def parse_theatre_page(payload):
    """Reduce one theatres-connection page to (theatres, has_next_page, end_cursor)."""
    connection = _viewer(payload, "graphql theatres").get("theatres")
    if not isinstance(connection, dict) or "edges" not in connection:
        raise ShapeChanged("graphql theatres: response has no TheatreConnection")
    page_info = connection.get("pageInfo") or {}
    theatres = tuple(_theatre(edge.get("node") or {}) for edge in connection.get("edges") or [])
    return theatres, bool(page_info.get("hasNextPage")), page_info.get("endCursor")


def _theatre(node):
    missing = [k for k in ("theatreId", "slug") if node.get(k) is None]
    if missing:
        raise ShapeChanged(f"graphql theatres: theatre missing {', '.join(missing)}")
    return Theatre(
        theatre_id=parse_int(node["theatreId"], "graphql theatres: theatreId"),
        slug=node["slug"],
        name=node.get("name") or "",
        city=node.get("city") or "",
        state=node.get("state") or "",
        postal_code=node.get("postalCode") or "",
        latitude=node.get("latitude"),
        longitude=node.get("longitude"),
        market_slug=node.get("marketSlug") or "",
        utc_offset=node.get("utcOffset") or "",
        timezone_abbreviation=node.get("timezoneAbbreviation") or "",
        ticketable=bool(node.get("ticketable")),
        is_in_outage=bool(node.get("isInOutage")),
    )


def parse_discovery(payload, theatre_slug):
    """Reduce a discovery response to pre-enriched DiscoveredShowtime rows.

    The same Showtime can appear under several format tabs (e.g. both "IMAX" and
    "IMAX 70MM"), so rows are unioned across all tabs and groups and deduped by
    showtime ID. Each row carries its *own* Format-group attributes, so which tab it
    was found under never decides its format. An empty result is an answer — a theatre
    with nothing scheduled that day — never an exception; a *truncated* result is not,
    and raises DiscoveryIncomplete.
    """
    viewer = _viewer(payload, "graphql discovery")
    if "theatre" not in viewer:
        raise ShapeChanged("graphql discovery: response has no theatre field")
    theatre = viewer["theatre"]
    if theatre is None:
        # AMC answered: nothing lives at this slug. Stale config, not a quiet day.
        raise TheatreNotFound(f"GraphQL says there is no theatre at slug {theatre_slug!r}")
    if not isinstance(theatre, dict):
        raise ShapeChanged(f"graphql discovery: no theatre object in response for {theatre_slug!r}")
    if theatre.get("theatreId") is None:
        raise ShapeChanged("graphql discovery: theatre has no theatreId")

    rows, seen = [], set()
    for item in (theatre.get("formats") or {}).get("items") or []:
        groups = item.get("groups") or {}
        _refuse_truncation(groups, "groups", theatre_slug)
        for group_edge in groups.get("edges") or []:
            showtimes = ((group_edge.get("node") or {}).get("showtimes") or {})
            _refuse_truncation(showtimes, "showtimes", theatre_slug)
            for edge in showtimes.get("edges") or []:
                row = _discovered_row(edge.get("node") or {}, theatre, theatre_slug)
                if row.showtime_id not in seen:
                    seen.add(row.showtime_id)
                    rows.append(row)
    return tuple(rows)


def _refuse_truncation(connection, what, theatre_slug):
    """A capped connection that has more pages means Showtimes we never saw.

    Discovery is the only way into the Registry, so a partial answer must be louder
    than a quiet short list — the caller cannot tell the two apart otherwise.
    """
    if (connection.get("pageInfo") or {}).get("hasNextPage"):
        raise DiscoveryIncomplete(
            f"graphql discovery: {theatre_slug} has more {what} than one query "
            f"carries — raise the page size or paginate before trusting the Registry"
        )


def _discovered_row(node, theatre, theatre_slug):
    fmt = _format_of(node)
    movie = node.get("movie") or {}
    missing = [
        k
        for k, v in {
            "showtimeId": node.get("showtimeId"),
            "movie.movieId": movie.get("movieId"),
            "format.code": fmt.get("code"),
        }.items()
        if v is None
    ]
    if missing:
        raise ShapeChanged(f"graphql discovery: showtime row missing {', '.join(missing)}")
    showtime_id = parse_int(node["showtimeId"], "graphql discovery: showtimeId")
    auditorium = node.get("auditorium")
    return DiscoveredShowtime(
        showtime_id=showtime_id,
        theatre_id=parse_int(theatre["theatreId"], "graphql discovery: theatreId", showtime_id),
        theatre_slug=theatre.get("slug") or theatre_slug,
        theatre_name=theatre.get("name") or "",
        movie_id=parse_int(movie["movieId"], "graphql discovery: movie.movieId", showtime_id),
        movie_name=movie.get("name") or "",
        movie_slug=movie.get("slug") or "",
        format_code=fmt["code"],
        format_name=fmt.get("name") or "",
        starts_at_utc=parse_starts_at(node.get("showDateTimeUtc"), "graphql discovery"),
        auditorium=(
            parse_int(auditorium, "graphql discovery: auditorium", showtime_id)
            if auditorium is not None
            else None
        ),
        status=str(node.get("status") or ""),
        is_reserved_seating=bool(node.get("isReservedSeating")),
    )


def parse_seat_response(payload, showtime_id):
    """Reduce a seat-query response to a SeatPage."""
    viewer = _viewer(payload, "graphql seat read")
    # `showtime: null` is AMC saying the ID is dead; the *key* missing means the schema
    # moved under us. Telling them apart matters: one remedy is "pass a fresh ID", the
    # other is "every Watch is blind until fetch-core is updated".
    if "showtime" not in viewer:
        raise ShapeChanged("graphql seat read: response has no showtime field", showtime_id)
    node = viewer["showtime"]
    if node is None:
        raise ShowtimeNotFound("GraphQL says there is no such showtime", showtime_id)
    if not isinstance(node, dict):
        raise ShapeChanged("graphql seat read: response has no showtime object", showtime_id)
    layout = node.get("seatingLayout")
    if not isinstance(layout, dict) or "seats" not in layout:
        raise ShapeChanged("graphql seat read: showtime has no seatingLayout", showtime_id)
    try:
        return SeatPage(seats=parse_seats(layout), **showtime_fields(node))
    except ShapeChanged as e:
        # The shared extractors do not know which showtime they are reading; the ID is
        # the one thing an operator needs to reproduce the loudest failure class.
        if e.showtime_id is None:
            e.showtime_id = showtime_id
        raise
