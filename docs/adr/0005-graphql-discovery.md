# Automated showtime discovery via AMC's public GraphQL (supersedes 0001)

AMC's own web app fetches its showtime listings *and* seat maps from `POST
https://graph.amctheatres.com/`, authorized by ordinary browser cookies/Origin — no vendor
key, no approval, and **not** behind the Queue-it waiting room (a bare API-host request
returns a normal GraphQL error, not a queue 302; confirmed live 2026-08-14, see
`docs/research/amc-discovery-mechanisms.md`). The endpoint exposes theatre
enumeration/search (`viewer.theatres`), per-theatre showtime discovery
(`viewer.theatre(slug).formats…showtimes`, pre-enriched with movie, format, start time,
auditorium), and seat layouts (`viewer.showtime(id).seatingLayout`) — the whole
discovery→seats pipeline. Discovery is therefore **fully automated**: the Registry grows
by GraphQL enumeration of the (theatre, movie) set across active Watches, and human
Contribution and the Bookmarklet are removed entirely.

## Considered options

- **Automated GraphQL discovery** (chosen) — one open host gives enumeration + discovery +
  seats as clean JSON, off the Queue-it path, no key. The showtime rows arrive
  pre-enriched, so there is no separate enrichment fetch. Discovery latency becomes
  machine-bounded.
- **Official AMC vendor API** (`api.amctheatres.com`, `X-AMC-Vendor-Key`) — a real,
  sanctioned, Cloudflare-but-not-Queue-it host, and a viable hedge. Rejected as a
  *dependency*: ~10-day key lead, and whether live seat availability sits in the free
  catalog tier is unverified. Kept in reserve, not on the critical path.
- **Keeping human Contribution / the Bookmarklet** — rejected: automation makes the
  paste-IDs flow pointless, and maintaining it as a fallback is extra work the owner
  explicitly declined.
- **RSC HTML listing scrape** — dead: the `www.amctheatres.com` listing surface 302s into
  Queue-it (ADR-0001's original finding, unchanged).

## Consequences

- **Transport amends 0003.** `graph.amctheatres.com` 403s both plain python-requests and
  curl, so discovery and the GraphQL seat read use `curl_cffi` (browser TLS/JA3
  impersonation) + a warmed cookie jar + the session-date cookie (`nowInDays` /
  `lastViewedDate` drive the business date). Politeness = fingerprint + cookie jar + jitter
  + a small worker pool.
- **Topology of 0002 is unchanged.** Discovery folds into the poller as an additional pass
  — no 4th service.
- **The Polling Budget gains a discovery lane** — a slow enumeration lane beside the seat
  lanes; the hard global cap still holds.
- **ADR-0001 is superseded.** Seat Pages are no longer the only source, and human
  Contribution is gone.
- **The smoke test of 0004** now also verifies `graph.amctheatres.com` reachability via
  `curl_cffi`, alongside the existing seat-page GET.
- **The RSC seat-page fetcher (`fetch_core`, plain requests against
  `www.amctheatres.com/showtimes/<id>/seats`) remains a seat-read fallback only** — never
  discovery. It fails independently of the GraphQL surface.
- **Single-source risk:** if AMC ever clamps the GraphQL surface, the system has no data
  source — but discovery latency is now machine-bounded, not bounded by a human noticing.
