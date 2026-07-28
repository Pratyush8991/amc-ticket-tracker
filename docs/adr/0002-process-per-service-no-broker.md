# Process-per-service in one monorepo, coordinated through Postgres, no broker

The tracker is becoming an invite-only hosted service with ambitions of growing into a
full app. We split into separately deployable processes (web, poller, matcher+notifier)
for deploy isolation and service discipline, but they live in one monorepo, share one
Postgres, and coordinate via DB-backed work tables — no message broker, no inter-service
HTTP, no per-service contract versioning.

## Considered options

- **Full split with a broker from day 1** (original inclination) — rejected: at
  friends-scale it buys four failure modes, lockstep contract migrations for a solo dev,
  and queue hops on the time-critical fetch→match→notify path, in exchange for scale
  headroom the domain cannot use — the poller must *never* scale out, because AMC's bot
  tolerance (not compute) is the bottleneck.
- **Modular monolith** — cheapest to run, but loses independent deploy/restart of the
  poller during an on-sale window, which is exactly when the web app churns most.
- **Polyrepo** — explicitly considered and rejected (2026-07-22). Repo layout is
  orthogonal to service topology: the services deploy independently regardless of where
  their source lives. Polyrepo buys per-*team* ownership boundaries this project doesn't
  have, and costs a solo dev the atomic cross-service commit — one schema change would
  become three coordinated PRs plus versioned internal packages for the shared fetch
  core and models.

## Consequences

Adding a broker later is a localized change (replace work-table polling with a consumer)
because service boundaries already exist. All processes must be broker-agnostic: no
in-process shared state between services, all coordination through the DB.
