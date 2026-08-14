"""Seat Page GET + RSC-payload parse — the system's only AMC data source (ADR-0001)."""

from .client import DEFAULT_TIMEOUT, HEADERS, fetch_seat_page, seat_page_url
from .errors import (
    AccessBlocked,
    QueueWalled,
    RateLimited,
    FetchError,
    ShapeChanged,
    FetchUnavailable,
    ShowtimeNotFound,
)
from .model import BOOKABLE_TYPES, Seat, SeatPage
from .parse import parse_seat_page

__all__ = [
    "BOOKABLE_TYPES",
    "DEFAULT_TIMEOUT",
    "HEADERS",
    "AccessBlocked",
    "QueueWalled",
    "RateLimited",
    "Seat",
    "SeatPage",
    "FetchError",
    "ShapeChanged",
    "FetchUnavailable",
    "ShowtimeNotFound",
    "fetch_seat_page",
    "parse_seat_page",
    "seat_page_url",
]
