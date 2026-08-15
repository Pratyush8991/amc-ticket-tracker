# amc-ticket-tracker

Watches AMC seat maps and pings your phone the moment enough **adjacent, actually
bookable** seats open up in a block you care about. You get the notification; you book
manually in the app.

It began as a single-user script built to grab a rescheduled **IMAX 70mm** ticket to
*The Odyssey* at AMC Metreon 16 — which worked, catching center-block pairs on two
different dates. It is now being rebuilt as a small invite-only hosted service so several
people can watch different movies, formats and seat blocks at once. That rebuild is in
progress; see **Status** below for what actually runs today.

- The vocabulary is in [`CONTEXT.md`](CONTEXT.md).
- The four load-bearing decisions are in [`docs/adr/`](docs/adr/).

## How it works

AMC's own web app reads showtimes and seat maps from a public GraphQL endpoint:

```
POST https://graph.amctheatres.com/
```

Ordinary browser cookies authorize it — **no vendor key, no headless browser** — and it
sits **off the Queue-it path** that walls AMC's HTML listing pages. Three queries cover the
whole pipeline:

- **`viewer.theatres(query, coordinates, …)`** seeds and searches the **Theatre** registry
  (`query: "AMC"` lists every theatre, paged by cursor). Each node carries `theatreId`,
  `slug`, `name`, location and formats.
- **`viewer.theatre(slug){ … showtimes … }`** is **Discovery**: it enumerates a theatre's
  showtimes, and the rows come back **pre-enriched** — `showtimeId`, `showDateTimeUtc`,
  `status`, `auditorium`, format `code`/`name`, and `movie` — so there is no second
  enrichment fetch. The target business date rides a `session` cookie, so the poller loops
  forward day by day.
- **`viewer.showtime(id){ seatingLayout { … } }`** returns the seat map as clean JSON
  (`name`, `row`, `column`, `available`, `seatStatus`, `type`, `shouldDisplay`).

Discovery is fully automated: the poller enumerates the theatres and movies its active
Watches care about and feeds the `showtimeId`s straight into the Registry. No human pastes
IDs (ADR-0005).

The older seat-page scrape survives as a **seat-read fallback only**. The same
`seatingLayout` is embedded in the server-rendered page at
`www.amctheatres.com/showtimes/<id>/seats` (in the Next.js RSC payload), which a plain
`requests.get()` with a browser User-Agent still fetches. It fails independently of
GraphQL, so it backstops seat reads — but it is never a discovery route.

Three things fall out of the seat layout grid, and all three still hold:

- **Adjacency** is consecutive grid *columns* in the same grid row. Aisles and
  wheelchair/companion seats occupy their own columns, so they break adjacency for free.
- **Printed seat names are a different coordinate system.** In the Metreon IMAX house, K34
  sits at grid column 1 and K1 at column 34 — numbers descend as columns ascend. Adjacency
  is only ever computed on grid coordinates.
- **Available is not bookable.** AMC marks wheelchair and companion seats available too,
  so filtering by seat *type* (`CanReserve`) is what keeps them from firing false alerts.

## Status

The rebuild is landing in slices, tracked in GitHub issues. What exists today:

| Area | State |
| --- | --- |
| `fetch_core` — RSC seat-page GET + parse, error taxonomy (seat-read fallback) | working |
| `amc-watch smoke-test` — the first act on any new box | working |
| Test harness — ephemeral Postgres, Alembic baseline, recorded fixtures | working |
| `discovery` — GraphQL theatre + showtime fetch (`curl_cffi`), cookie/session-date warming | planned |
| `registry` — automated discovery, pre-enriched showtimes | skeleton (#3) |
| `watching` — selectors, lifecycle, Opening computation | skeleton (#4, #6) |
| `alerting` — ntfy Channel, dedup ledger | skeleton (#4) |
| `web` — invites, watch management, seat picker | skeleton (#8–#12) |

The single-user script this grew out of — flat `config.json`, `state.json`, the Actions
cron and the launchd plist — has been retired. It is preserved in git history (before
commit `4384f47`), including the 59 Odyssey showtime IDs it watched.

## Quick start

```bash
uv sync --extra dev
```

Before anything else on a new machine, check that it can reach AMC at all:

```bash
uv run amc-watch smoke-test
```

```
GraphQL  POST https://graph.amctheatres.com/ (curl_cffi)
PASS: graph.amctheatres.com reachable — theatre + showtime queries answer
Seats    GET https://www.amctheatres.com/showtimes/145377422/seats
PASS: The Odyssey - IMAX 70MM (imax70mm) at AMC Metreon 16, 2026-08-15 17:00 UTC
       437 seats in the layout, 1 bookable right now
```

It checks both surfaces the system depends on: the GraphQL host (reached with `curl_cffi`,
since plain `requests`/`curl` get a 403 there) and the RSC seat-page host (plain
`requests`). A `FAIL` tells you which wall you hit and what to do about it — a queue
redirect, a 403, a 429, a dead showtime ID, or a changed page/response shape are all
reported distinctly, because "AMC blocked us" and "no seats are open" must never look
alike.

Discovery supplies showtime IDs automatically now, so you never hunt one down by hand. The
smoke test still pins a specific ID for its seat-read check; that default rots within days,
so override it with `--showtime-id <id>` or `AMC_SMOKE_TEST_SHOWTIME_ID` when it goes
stale. ID waves are not contiguous (Aug 9 was `1446969xx`, Aug 15 `1453774xx`) — one more
reason discovery enumerates them rather than guessing.

## Tests

```bash
uv run --extra dev pytest          # unit + integration; never touches AMC
uv run --extra dev pytest -m live  # the one test that really hits AMC
```

The suite fakes exactly one thing: the outbound HTTP edge. AMC is served from Seat Page
payloads recorded off the real site, so unescaping, parsing and the error taxonomy all run
for real — a parser regression fails the build. The fixtures are genuinely missing row I
and genuinely have wheelchair seats open while standard seats are sold, so the two nastiest
cases are recorded rather than imagined. Re-record with
`python tools/record_seat_page_fixture.py --showtime-id <id>`.

Postgres is real, not faked: the suite boots a throwaway container locally, or uses
`DATABASE_URL` if you set one (which is what CI does).

## Why you still book manually

Checkout needs a login, a CAPTCHA and your AMC Stubs / A-List benefits, and AMC actively
flags automation. The tool does the boring part (watching) and you do the sensitive part
(buying). That split is permanent, not a TODO — don't point Selenium or Playwright at
checkout.

## Honest notes

- **It's a scraper, so it's brittle.** If AMC changes the payload shape — the RSC page or
  the GraphQL schema — you get a loud `ShapeChanged`, never a quiet "no seats"; a
  truncated discovery gets its own `DiscoveryIncomplete`. The fix lives in
  `src/amc_watch/fetch_core/parse.py` and `fetch_core/graphql/`.
- **The transport is load-bearing, and it's two-tier.** The GraphQL host
  (`graph.amctheatres.com`) 403s plain `requests` *and* `curl`; it answers only a
  browser-accurate TLS fingerprint, so discovery runs on `curl_cffi` with a warmed cookie
  jar and the session-date cookie. The RSC seat-page host still passes with plain
  python-requests and browser headers. Don't casually port either (ADR-0003, amended).
- **AMC's tolerance is the bottleneck, not compute.** Polling is budgeted globally on
  purpose. A handful of hand-run probes from one box was enough to draw a 429 on
  2026-07-28, which is roughly how much headroom there is.
- **Datacenter IPs are not proven.** Every successful fetch on record came from a
  residential connection; from a datacenter IP the queue wall appears intermittently. Run
  the smoke test on any new box before building on it (ADR-0004).
- Not affiliated with or endorsed by AMC; check their terms before you run it.
