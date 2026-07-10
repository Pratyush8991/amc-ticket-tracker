# amc-ticket-tracker

Watches AMC Metreon 16 (San Francisco) seat maps for **The Odyssey — IMAX 70mm**
and pushes an [ntfy.sh](https://ntfy.sh) notification the moment **two adjacent
free seats** appear in the center block (rows H–N, seats 7–21), across every
showtime you list (e.g. Jul 19 – Aug 1). You book manually via the link.

**No API key, no cookies, no login required.** The seat page
`https://www.amctheatres.com/showtimes/<ID>/seats` is server-rendered and embeds
the full seat layout in its HTML; the script just fetches it and parses it.
(Verified live: it correctly found an open `N7–N8` pair on a real showtime.)

Why hybrid (auto-find, manual-buy): AMC checkout needs your login + Stubs/A-List
benefit + CAPTCHA, and their telemetry flags automation (`webdriverDetected`).
So we *notify fast* and you buy in the app. Do **not** point Selenium/Playwright
at it — a plain HTTP GET is both simpler and less likely to be blocked.

## Setup

### 1. Collect showtime IDs (the only manual step — ~5 min, one time)
For each IMAX 70mm showtime in your date range:
1. On amctheatres.com, open the movie at AMC Metreon 16, click the 70mm showtime
   through to the **seat map**.
2. The address bar reads `.../showtimes/144251502/seats` — the number is the ID.
3. Collect all of them (dates Jul 19 – Aug 1).

> Auto-discovery isn't possible without AMC's vendor key: the *listing* pages
> load showtimes client-side. The *seat* pages (what we poll) do not — hence no
> key needed for the actual watching.

### 2. Fill in config
```bash
cp config.example.json config.json
```
Add one `{ "id", "label" }` per showtime. Rows/seat-number block is already set
to H–N / 7–21 (note: AMC skips row **I**, so that's really H,J,K,L,M,N).
Only `CanReserve` seats count, so **Wheelchair and Companion seats never trigger
an alert** even though AMC marks them "available".

A populated `config.json` ships with all Odyssey 70mm showtimes Jul 16 – Jul 26;
add the Jul 27 – Aug 1 shows the same way as they open.

### 3. Notifications (ntfy — no account, no key)
1. Install the **ntfy** app, subscribe to a random topic name, e.g. `amc-odyssey-7fq3z`.
2. GitHub → **Settings → Secrets and variables → Actions → New secret**:
   name `NTFY_TOPIC`, value = that topic. (For local runs, pass it as an env var.)

### 4. Turn on the cron
- Push this repo to GitHub as a **PRIVATE** repo.
- `.github/workflows/watch.yml` triggers every 5 min and internally polls
  ~every 60 s for ~4.5 min, giving near-continuous coverage.
- Kick off a first run: **Actions → AMC seat watch → Run workflow**.
- Watch it work with the bundled TEST showtime first, then remove that entry.

## Local run / VPS (more reliable than GitHub cron)
```bash
uv venv --python 3.12
uv pip install -r requirements.txt
NTFY_TOPIC=your-topic uv run python amc_watch.py
```
For a true 24/7 60-second loop, set `"run_duration_seconds": 999999999` in
config.json and run it under `launchd`/`systemd`/`pm2`.

**Smoke-test notifications** (no open seats needed): `uv run python amc_watch.py
--test` temporarily counts Wheelchair/Companion seats (usually available) and
checks only the first showtime, so your phone should buzz — proving the ntfy
path. It never saves state and doesn't affect normal runs.

## Notes
- **Rate/blocking:** ~13 pages every ~60 s with jitter is well under 1 req/s —
  looks human. Don't drop `poll_seconds` much or you risk a 429.
- **State:** `state.json` remembers alerted pairs so you're not re-pinged, and
  re-notifies if a pair closes then reopens. It's committed back each run.
- **GitHub cron caveat:** scheduled runs are best-effort — can be delayed or
  skipped under load. A VPS/Pi loop avoids that entirely (same code).
- **If it ever stops finding seats / errors with "seatingLayout not found":**
  AMC changed the page shape. The parser lives in `extract_layout()` /
  `parse_seats()` in `amc_watch.py`.

## Reference IDs
- Movie: The Odyssey → `movie_id 76238`
- Theatre: AMC Metreon 16, SF → `theatre_id 2325`
- Seat page pattern: `https://www.amctheatres.com/showtimes/<showtime_id>/seats`
