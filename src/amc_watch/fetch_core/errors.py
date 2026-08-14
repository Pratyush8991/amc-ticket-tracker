"""Failure modes of a fetch against AMC, shared by both backends.

The distinction these types draw is the operator-facing one from ADR-0004/0005: an empty
result means *AMC said there is nothing there*, an exception means *we never got a
trustworthy answer*. Collapsing the two is how a watcher silently stops watching — so "no
open seats" (or a theatre with no showtimes) is never an exception, and "AMC changed
shape" is never an empty list.

One taxonomy covers both fetch surfaces — the RSC Seat Page GET on `www.amctheatres.com`
and the GraphQL queries on `graph.amctheatres.com` — because the poller reacts to the
category, not the surface: AccessBlocked triggers the same contingency and RateLimited
stretches the same Polling Budget whichever host raised it.
"""


class FetchError(Exception):
    """Base: AMC did not yield a trustworthy answer."""

    def __init__(self, message, showtime_id=None):
        super().__init__(message)
        self.showtime_id = showtime_id


class QueueWalled(FetchError):
    """Redirected into the Queue-it waiting room.

    Verified intermittent from datacenter IPs (2026-07-28) and the standing behavior of
    every non-seat page since AMC's 2026-07 hardening. Retryable: the same ID often 200s
    moments later, so this is a backoff signal, not a dead showtime. The GraphQL host is
    not behind Queue-it (ADR-0005) but the classification is kept there too, so a future
    clampdown surfaces by name instead of as a mystery failure.
    """


class AccessBlocked(FetchError):
    """Refused outright (403 / Cloudflare challenge).

    Distinct from QueueWalled: the queue is a line, this is a door. Sustained
    AccessBlocked from a box is the ADR-0004 datacenter-IP contingency firing.
    """


class ShowtimeNotFound(FetchError):
    """The showtime ID is dead or was never real (404, or a null GraphQL showtime)."""


class TheatreNotFound(FetchError):
    """AMC answered, but no theatre exists at the requested slug.

    Distinct from a theatre with zero showtimes (an empty, successful discovery):
    this means the slug itself is wrong — stale config, not a quiet day.
    """


class RateLimited(FetchError):
    """429 — we asked too often.

    Unlike AccessBlocked this is self-inflicted and the remedy is ours: spend less
    Polling Budget. Observed after only a handful of manual probes on 2026-07-28, which
    is a useful calibration for how little headroom the fast lane really has.
    """


class FetchUnavailable(FetchError):
    """Transport failure or an unexpected HTTP status. Retryable."""


class ShapeChanged(FetchError):
    """Got an answer, but not one that parses to what we asked for.

    The loudest failure in the system: it means AMC changed the payload — the RSC page
    lost its seatingLayout, or the GraphQL response lost the fields we query — and every
    Watch is now blind. Never conflate with "no open seats".
    """
