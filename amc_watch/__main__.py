"""CLI entry point: poll every configured showtime and alert on newly-open pairs.

    python -m amc_watch            # timed loop sized to fit one CI job
    python -m amc_watch --forever  # run indefinitely (launchd/systemd on an always-on box)
    python -m amc_watch --test     # smoke-test the notification path (never saves state)

Fetches all showtimes concurrently with a small thread pool — fast, but not a burst of
requests that trips AMC's bot detection. Notify/state handling stays single-threaded.
"""

import os
import random
import sys
import time
from concurrent.futures import ThreadPoolExecutor

import requests

from .config import load_config, load_state, save_state
from .notify import notify
from .seats import SEATS_URL, fetch_pairs


def _fetch_one(st, cfg):
    """Worker: fetch adjacent pairs for one showtime, using its own Session
    (requests.Session isn't guaranteed thread-safe, so don't share one)."""
    sid = str(st["id"])
    try:
        with requests.Session() as s:
            return st, fetch_pairs(sid, cfg, s), None
    except Exception as e:  # noqa: BLE001 — one bad showtime shouldn't stop others
        return st, None, e


def check_all(cfg, state, save=True):
    topic = os.environ.get("NTFY_TOPIC") or cfg.get("ntfy_topic")
    if not topic:
        sys.exit("No ntfy topic (env NTFY_TOPIC or config.json ntfy_topic).")
    notified = state.setdefault("notified", {})
    changed = False

    # Fetch all showtimes concurrently with a modest pool: fast, but not a 27-request
    # burst that trips AMC's WAF. Notify/state handling stays single-threaded.
    showtimes = cfg["showtimes"]
    workers = max(1, min(cfg.get("max_workers", 6), len(showtimes)))
    with ThreadPoolExecutor(max_workers=workers) as ex:
        results = list(ex.map(lambda st: _fetch_one(st, cfg), showtimes))

    for st, pairs, err in results:
        sid = str(st["id"])
        label = st.get("label", sid)
        if err is not None:
            print(f"[warn] {label}: {err}")
            continue
        current = {"-".join(sorted(p)) for p in pairs}
        seen = set(notified.get(sid, []))
        for pair_id in sorted(current - seen):
            print(f"[HIT] {label}: {pair_id}")
            notify(
                topic,
                title=f"2 seats: {label}",
                message=f"🎬 Seats {pair_id} open for Odyssey 70mm.\nTap to book now.",
                click_url=SEATS_URL.format(id=sid),
            )
        if seen != current:
            notified[sid] = sorted(current)
            changed = True

    if changed and save:
        save_state(state)


def run_test(cfg):
    """Smoke-test the notification path: widen seat types to include the always-present
    Wheelchair/Companion seats so an alert actually fires, hit only the first showtime,
    and never touch saved state."""
    test_cfg = {
        **cfg,
        "bookable_types": sorted(set(cfg.get("bookable_types", ["CanReserve"]))
                                 | {"Wheelchair", "Companion"}),
        "showtimes": cfg["showtimes"][:1],
    }
    label = test_cfg["showtimes"][0]["label"] if test_cfg["showtimes"] else "?"
    print(f"[TEST] Widened seat types, checking only: {label}")
    print("[TEST] If any seats are open there, your phone should buzz. State not saved.")
    check_all(test_cfg, {}, save=False)
    print("[TEST] Done. If nothing fired, that showtime has no open seats at all "
          "right now — try another as the first entry, or check the NTFY_TOPIC.")


def main():
    test = "--test" in sys.argv
    # --forever: run indefinitely (for launchd/systemd on an always-on machine),
    # ignoring run_duration_seconds. Default: the timed loop that fits a CI job.
    forever = "--forever" in sys.argv
    cfg = load_config()

    if test:
        run_test(cfg)
        return

    state = load_state()
    poll = cfg.get("poll_seconds", 60)
    deadline = float("inf") if forever else time.time() + cfg.get("run_duration_seconds", 270)
    if forever:
        print(f"[forever] watching {len(cfg['showtimes'])} showtimes; poll ~{poll}s. "
              "Stop with launchctl bootout / Ctrl-C.", flush=True)
    while True:
        check_all(cfg, state)
        if forever:
            print(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] pass complete", flush=True)
        if time.time() + poll >= deadline:
            break
        time.sleep(poll + random.uniform(-5, 5))


if __name__ == "__main__":
    main()
