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

AMC's seat page

```
https://www.amctheatres.com/showtimes/<showtime_id>/seats
```

is **server-rendered**: the entire seat layout is embedded in the page (a `seatingLayout`
object in the Next.js RSC payload), along with the movie, theatre, format and start time.
So a plain `requests.get()` with a browser User-Agent returns everything — and a *bare
showtime ID is enough*, because the page describes itself. No vendor key, no headless
browser.

That matters more than it sounds, because AMC's listing and theatre pages now redirect
into a Queue-it waiting room. Seat pages are the only door left, so showtime IDs enter the
system by human contribution rather than by crawling (ADR-0001).

Three things fall out of the layout grid:

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
| `fetch_core` — Seat Page GET + RSC parse, error taxonomy | working |
| `amc-watch smoke-test` — the first act on any new box | working |
| Test harness — ephemeral Postgres, Alembic baseline, recorded fixtures | working |
| `registry` — contribution + enrichment | skeleton (#3) |
| `watching` — selectors, lifecycle, Opening computation | skeleton (#4, #6) |
| `alerting` — ntfy Channel, dedup ledger | skeleton (#4) |
| `web` — invites, watch management, seat picker, bookmarklet | skeleton (#8–#12) |

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
GET https://www.amctheatres.com/showtimes/144696969/seats
PASS: The Odyssey - IMAX 70MM (imax70mm) at AMC Metreon 16, 2026-08-09 17:00 UTC
      437 seats in the layout, 1 bookable right now
```

A `FAIL` tells you which wall you hit and what to do about it — a queue redirect, a 403,
a 429, a dead showtime ID, or a changed page shape are all reported distinctly, because
"AMC blocked us" and "no seats are open" must never look alike. Showtimes pass, so the
default ID rots; override it with `--showtime-id <id>`.

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

- **It's a scraper, so it's brittle.** If AMC changes the page shape you get a loud
  `SeatPageShapeChanged`, never a quiet "no seats". The fix lives in
  `src/amc_watch/fetch_core/parse.py`.
- **The transport is load-bearing.** python-requests with browser headers passes AMC's
  Cloudflare hardening where curl gets a 403. Don't casually port it (ADR-0003).
- **AMC's tolerance is the bottleneck, not compute.** Polling is budgeted globally on
  purpose. A handful of hand-run probes from one box was enough to draw a 429 on
  2026-07-28, which is roughly how much headroom there is.
- **Datacenter IPs are not proven.** Every successful fetch on record came from a
  residential connection; from a datacenter IP the queue wall appears intermittently. Run
  the smoke test on any new box before building on it (ADR-0004).
- Not affiliated with or endorsed by AMC; check their terms before you run it.
