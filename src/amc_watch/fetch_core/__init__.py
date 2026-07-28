"""Seat Page GET + RSC-payload parse — the system's only AMC data source (ADR-0001)."""

from .client import DEFAULT_TIMEOUT, HEADERS, fetch_seat_page, seat_page_url
from .errors import (
    AccessBlocked,
    QueueWalled,
    SeatPageError,
    SeatPageShapeChanged,
    SeatPageUnavailable,
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
    "Seat",
    "SeatPage",
    "SeatPageError",
    "SeatPageShapeChanged",
    "SeatPageUnavailable",
    "ShowtimeNotFound",
    "fetch_seat_page",
    "parse_seat_page",
    "seat_page_url",
]
