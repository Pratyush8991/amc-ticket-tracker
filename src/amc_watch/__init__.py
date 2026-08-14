"""amc-watch — invite-only hosted seat-watching service for AMC Seat Pages.

One package, three deployable services (web, poller, matcher+notifier) coordinating
through one Postgres with no broker (ADR-0002). Domain seams are enforced by module
regardless of which process runs them:

    fetch_core  Seat Page GET + RSC parse — the only outbound AMC edge
    registry    contribution, enrichment, showtime storage
    watching    selector matching, lifecycle, Seat Criteria / Opening computation
    alerting    Channel interface, ntfy implementation, Alert dedup ledger
    web         API + UI + bookmarklet endpoint + invites/session auth
    services    the per-process entry points, each a thin shell over a run_once()

The ubiquitous language lives in CONTEXT.md; the load-bearing decisions in docs/adr/.
"""

__version__ = "0.1.0"
