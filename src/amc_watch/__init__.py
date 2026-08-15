"""amc-watch — invite-only hosted seat-watching service for AMC showtimes.

One package, three deployable services (web, poller, matcher+notifier) coordinating
through one Postgres with no broker (ADR-0002). Domain seams are enforced by module
regardless of which process runs them:

    fetch_core  the two outbound AMC edges — GraphQL discovery + seat reads over
                curl_cffi (primary), RSC Seat Page GET over requests (seat-read
                fallback only, never discovery); see ADR-0005
    registry    automated discovery, showtime storage
    watching    selector matching, lifecycle, Seat Criteria / Opening computation
    alerting    Channel interface, ntfy implementation, Alert dedup ledger
    web         API + UI + invites/session auth
    services    the per-process entry points, each a thin shell over a run_once()

The ubiquitous language lives in CONTEXT.md; the load-bearing decisions in docs/adr/.
"""

__version__ = "0.1.0"
