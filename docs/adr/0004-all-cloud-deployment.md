# Everything runs in the cloud, including the poller

Web, poller, matcher+notifier, and Postgres all deploy to one cloud box (systemd unit
per service). A home-residential poller was considered — every current proof that Seat
Pages accept plain HTTP comes from a residential IP, and datacenter-IP access is
unverified since AMC's 2026-07 Queue-it/Cloudflare hardening — but rejected: a home
machine cannot reliably promise results (sleep, reboots, ISP), and unreliable polling
defeats the product.

## Consequences

The first act on any new box is a one-GET seat-page smoke test (expect 200 +
`seatingLayout`). If datacenter IPs turn out to be blocked, the fallback is re-homing
only the poller process (the no-broker topology of ADR-0002 makes that a config change,
not a redesign) — but that fallback is a contingency, not the plan.
