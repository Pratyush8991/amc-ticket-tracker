"""Failure modes of a Seat Page fetch.

The distinction these types draw is the operator-facing one from ADR-0001/0004: an empty
result means *AMC said there are no seats*, an exception means *we never got a trustworthy
answer*. Collapsing the two is how a watcher silently stops watching — so "no open seats"
is never an exception, and "AMC changed shape" is never an empty list.
"""


class SeatPageError(Exception):
    """Base: the Seat Page did not yield a trustworthy answer."""

    def __init__(self, message, showtime_id=None):
        super().__init__(message)
        self.showtime_id = showtime_id


class QueueWalled(SeatPageError):
    """Redirected into the Queue-it waiting room.

    Verified intermittent from datacenter IPs (2026-07-28) and the standing behavior of
    every non-seat page since AMC's 2026-07 hardening. Retryable: the same ID often 200s
    moments later, so this is a backoff signal, not a dead showtime.
    """


class AccessBlocked(SeatPageError):
    """Refused outright (403 / Cloudflare challenge).

    Distinct from QueueWalled: the queue is a line, this is a door. Sustained
    AccessBlocked from a box is the ADR-0004 datacenter-IP contingency firing.
    """


class ShowtimeNotFound(SeatPageError):
    """404 — the showtime ID is dead or was never real (a Contribution typo)."""


class SeatPageUnavailable(SeatPageError):
    """Transport failure or an unexpected HTTP status. Retryable."""


class SeatPageShapeChanged(SeatPageError):
    """Got a page, but it did not contain a parseable seatingLayout.

    The loudest failure in the system: it means AMC changed the payload and every Watch
    is now blind. Never conflate with "no open seats".
    """
