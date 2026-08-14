"""fetch-core: the system's two outbound edges to AMC (ADR-0003 as amended, ADR-0005).

Two backends, one set of domain models and one error taxonomy:

- **GraphQL** (`graph.amctheatres.com` over curl_cffi) — theatre enumeration, showtime
  Discovery, and seat reads; the primary data surface.
- **RSC Seat Page** (`www.amctheatres.com` over python-requests) — a seat-read fallback
  only, never Discovery; it fails independently of the GraphQL surface.
"""

from .client import DEFAULT_TIMEOUT, HEADERS, fetch_seat_page, seat_page_url
from .errors import (
    AccessBlocked,
    FetchError,
    FetchUnavailable,
    QueueWalled,
    RateLimited,
    ShapeChanged,
    ShowtimeNotFound,
    TheatreNotFound,
)
from .graphql import (
    discover_showtimes,
    enumerate_theatres,
    fetch_seat_page_graphql,
    open_graphql_session,
)
from .model import BOOKABLE_TYPES, DiscoveredShowtime, Seat, SeatPage, Theatre
from .parse import parse_seat_page

__all__ = [
    "BOOKABLE_TYPES",
    "DEFAULT_TIMEOUT",
    "HEADERS",
    "AccessBlocked",
    "FetchError",
    "FetchUnavailable",
    "QueueWalled",
    "RateLimited",
    "Seat",
    "DiscoveredShowtime",
    "SeatPage",
    "ShapeChanged",
    "ShowtimeNotFound",
    "TheatreNotFound",
    "Theatre",
    "discover_showtimes",
    "enumerate_theatres",
    "fetch_seat_page",
    "fetch_seat_page_graphql",
    "open_graphql_session",
    "parse_seat_page",
    "seat_page_url",
]
