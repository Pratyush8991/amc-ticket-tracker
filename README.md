# amc-ticket-tracker

Watches AMC seat maps for a specific movie/format and pings your phone the moment
**two adjacent seats** open up in a block you care about. Built to grab a rescheduled
**IMAX 70mm** ticket to *The Odyssey* at AMC Metreon 16 (San Francisco) when every
showtime was sold out — it worked, catching center-block pairs on two different dates.

You get the notification; you book manually in the app. No login, no API key, no database.

## How it works

AMC's seat page

```
https://www.amctheatres.com/showtimes/<showtime_id>/seats
```

is **server-rendered** — the entire seat layout is embedded in the page HTML (a
`seatingLayout` object in the Next.js RSC payload). So a plain `requests.get()` with a
normal browser User-Agent returns every seat's state. No headless browser, no vendor key.

From there, the `amc_watch/` package splits into small, single-purpose modules
(`seats.py` for the fetch/parse/adjacency pipeline, `notify.py` for the push,
`config.py` for loading config/state, `__main__.py` for the poll loop):

- **Parse** the `seatingLayout` object out of the HTML.
- **Find adjacent pairs**: two seats are physically adjacent when they share a grid row
  and sit in consecutive grid columns. Aisles and wheelchair/companion seats occupy their
  own columns, so they break adjacency for free — no special-casing needed.
- **Filter** to your target rows/seat numbers and to standard `CanReserve` seats — AMC
  marks wheelchair and companion seats `available` too, so filtering by seat *type* is what
  keeps them from firing false alerts.
- **Notify** via [ntfy.sh](https://ntfy.sh) with a one-tap "Book now" link to the seat page.

Fetches all showtimes concurrently with a small thread pool (default 6 workers, ~9s a
pass) and polls every ~60s with a little jitter — fast enough to catch seats that free up
for a minute, gentle enough to stay under AMC's bot detection.

## Why you still book manually

Checkout needs a login, a CAPTCHA, and your AMC Stubs / A-List benefits, and AMC actively
flags automation. So the tool does the boring part (watching) and you do the sensitive part
(buying). That split is deliberate — don't point Selenium/Playwright at the checkout.

## Quick start

```bash
uv venv --python 3.12
uv pip install -r requirements.txt      # only dependency: requests

cp config.example.json config.json      # then fill in your showtimes (see below)
NTFY_TOPIC=your-topic-name uv run python -m amc_watch
```

Install the **ntfy** app on your phone and subscribe to `your-topic-name` (any random
string) to receive the pushes. Smoke-test the notification path without waiting for open
seats:

```bash
uv run python -m amc_watch --test
```

## Configuration

`config.json` is a flat list of showtimes plus the seat block to watch. The only manual
step is collecting showtime IDs: open a showtime through to its seat map on
amctheatres.com and copy the number from `.../showtimes/<ID>/seats`.

```json
{
  "poll_seconds": 60,
  "max_workers": 6,
  "target_rows": ["H", "I", "J", "K", "L", "M", "N"],
  "num_min": 7,
  "num_max": 21,
  "bookable_types": ["CanReserve"],
  "showtimes": [
    { "id": "143822475", "label": "Mon Jul 20, 6:00 PM (IMAX 70mm)" }
  ]
}
```

Note: AMC skips row **I**, so H–N is really H, J, K, L, M, N (listing "I" is harmless).
The `ntfy_topic` can live here as a local fallback, but prefer the `NTFY_TOPIC` env var.

## Running it continuously

Two options, same code:

- **Always-on machine (recommended).** `python -m amc_watch --forever` runs a true ~60s loop.
  On a Mac, `mac/com.prats.amc-ticket-tracker.plist` is a `launchd` template that keeps it
  alive across logins/crashes — see the comments in that file for install/uninstall.
- **GitHub Actions.** `.github/workflows/watch.yml` runs on a `*/5` cron with an internal
  poll loop to bridge the gap. Zero infra, but GitHub's scheduled cron is best-effort and
  can lag or drop runs — fine for casual use, worse for seats that vanish in a minute.

## Honest notes

- **No database.** "State" is a single local, git-ignored `state.json` file that remembers
  which pairs it already alerted, so you're not re-pinged every minute for the same open
  seats — and are re-pinged if a pair closes then reopens. That's the entire persistence
  layer. On an always-on runner it persists across restarts; in GitHub Actions it's per-run
  (the internal poll loop still dedups within a single run).
- **It's a scraper, so it's brittle.** If AMC changes the page shape you'll see
  `seatingLayout not found`; the fix lives in `amc_watch/seats.py`.
- **Be a good citizen.** This is a single-user personal tool with modest polling. Keep
  `max_workers` small and `poll_seconds` sane so you don't hammer the site or trip a 429,
  and complete the actual purchase yourself. Not affiliated with or endorsed by AMC; check
  their terms before you run it.

## Reference

- Seat page pattern: `https://www.amctheatres.com/showtimes/<showtime_id>/seats`
- Example target: The Odyssey (IMAX 70mm) @ AMC Metreon 16, SF
