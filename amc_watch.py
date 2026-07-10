#!/usr/bin/env python3
"""
AMC seat watcher — for each configured showtime, fetches the public seat-map
page, extracts the embedded seat data, and pushes an ntfy.sh notification when
TWO ADJACENT free seats appear inside a target block (rows H-N, seats 7-21 by
default). You tap the link and buy manually.

How it works (validated against the live site):
  * The seat page https://www.amctheatres.com/showtimes/{id}/seats is server-
    rendered. Its Next.js RSC payload embeds a `seatingLayout` object:
        {"columns":34,"rows":13,"seats":[
           {"available":false,"column":1,"row":1,"name":"","type":"NotASeat",...},
           {"available":true,"column":3,"row":1,"name":"A29","type":"CanReserve",...},
        ]}
  * `name` is the printed label ("N7" = row N seat 7). Grid `row`/`column` are
    integer coordinates; two real seats with the same `row` and consecutive
    `column` are physically adjacent (aisles are `NotASeat` cells, so they break
    adjacency automatically). No API key / cookies needed — just a browser UA.

Runs a short internal poll loop so one GitHub Actions trigger gives ~1-min
coverage for ~4.5 min. On a VPS, set run_duration_seconds huge for a true loop.
"""

import json
import os
import random
import re
import sys
import time
from collections import defaultdict
from pathlib import Path

import requests

ROOT = Path(__file__).parent
CONFIG_PATH = ROOT / "config.json"
STATE_PATH = ROOT / "state.json"

SEATS_URL = "https://www.amctheatres.com/showtimes/{id}/seats"
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/143.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}
_LAYOUT_RE = re.compile(r'"seatingLayout"\s*:\s*')
_NAME_RE = re.compile(r"^([A-Z]+)(\d+)$")


def load_json(path, default):
    return json.loads(path.read_text()) if path.exists() else default


def save_state(state):
    STATE_PATH.write_text(json.dumps(state, indent=2, sort_keys=True))


def extract_layout(html):
    """Pull the seatingLayout object out of the RSC payload. Returns dict or None."""
    # RSC escapes quotes as \" — unescape enough to decode the JSON fragment.
    text = html.replace('\\"', '"').replace("\\\\", "\\")
    m = _LAYOUT_RE.search(text)
    if not m:
        return None
    start = text.index("{", m.end())
    try:
        obj, _ = json.JSONDecoder().raw_decode(text, start)
    except json.JSONDecodeError:
        return None
    return obj if isinstance(obj, dict) and "seats" in obj else None


def parse_seats(layout):
    """Flatten to [{name,row_letter,number,grid_row,grid_col,available,seat_type}]."""
    out = []
    for s in layout.get("seats", []):
        if s.get("type") == "NotASeat":
            continue
        m = _NAME_RE.match(s.get("name") or "")
        if not m:
            continue
        out.append(
            {
                "name": s["name"],
                "row_letter": m.group(1),
                "number": int(m.group(2)),
                "grid_row": s.get("row"),
                "grid_col": s.get("column"),
                "available": bool(s.get("available")),
                "seat_type": s.get("type"),
            }
        )
    return out


def find_adjacent_pairs(seats, cfg):
    """Return list of frozenset({nameA, nameB}) for adjacent free seats in block.

    Only `bookable_types` (default: CanReserve) count — this excludes Wheelchair
    and Companion seats, which show as available but aren't standard seats. A
    companion/wheelchair seat between two reservable seats occupies a grid column,
    so it also correctly breaks adjacency.
    """
    rows = set(cfg["target_rows"])
    lo, hi = cfg["num_min"], cfg["num_max"]
    bookable = set(cfg.get("bookable_types", ["CanReserve"]))
    by_row = defaultdict(dict)  # grid_row -> {grid_col: name}
    for s in seats:
        if (
            s["available"]
            and s["seat_type"] in bookable
            and s["row_letter"] in rows
            and lo <= s["number"] <= hi
            and s["grid_col"] is not None
        ):
            by_row[s["grid_row"]][s["grid_col"]] = s["name"]

    pairs = []
    for cols in by_row.values():
        for c in sorted(cols):
            if c + 1 in cols:
                pairs.append(frozenset({cols[c], cols[c + 1]}))
    return pairs


def fetch_pairs(showtime_id, cfg, session):
    resp = session.get(SEATS_URL.format(id=showtime_id), headers=HEADERS, timeout=25)
    resp.raise_for_status()
    layout = extract_layout(resp.text)
    if layout is None:
        raise ValueError("seatingLayout not found (page shape changed or blocked)")
    return find_adjacent_pairs(parse_seats(layout), cfg)


def notify(topic, title, message, click_url):
    # HTTP header values must be latin-1; strip anything that isn't (e.g. emoji).
    # Emoji still show via the ASCII `Tags` field. The message BODY is UTF-8, so
    # rich text/emoji belong there, not in headers.
    def h(v):
        return v.encode("latin-1", "ignore").decode("latin-1")

    requests.post(
        f"https://ntfy.sh/{topic}",
        data=message.encode("utf-8"),
        headers={
            "Title": h(title),
            "Priority": "high",
            "Tags": "clapper,fire",
            "Click": h(click_url),
            "Actions": h(f"view, Book now, {click_url}"),
        },
        timeout=15,
    )


def check_all(cfg, state, session, save=True):
    topic = os.environ.get("NTFY_TOPIC") or cfg.get("ntfy_topic")
    if not topic:
        sys.exit("No ntfy topic (env NTFY_TOPIC or config.json ntfy_topic).")
    notified = state.setdefault("notified", {})
    changed = False

    for st in cfg["showtimes"]:
        sid = str(st["id"])
        label = st.get("label", sid)
        url = SEATS_URL.format(id=sid)
        try:
            pairs = fetch_pairs(sid, cfg, session)
        except Exception as e:  # noqa: BLE001 — one bad showtime shouldn't stop others
            print(f"[warn] {label}: {e}")
            continue

        current = {"-".join(sorted(p)) for p in pairs}
        seen = set(notified.get(sid, []))
        for pair_id in sorted(current - seen):
            print(f"[HIT] {label}: {pair_id}")
            notify(
                topic,
                title=f"2 seats: {label}",
                message=f"🎬 Seats {pair_id} open for Odyssey 70mm.\nTap to book now.",
                click_url=url,
            )
        if seen != current:
            notified[sid] = sorted(current)
            changed = True

    if changed and save:
        save_state(state)


def run_test(cfg, session):
    """Smoke-test the notification path: widen seat types to include the always-
    present Wheelchair/Companion seats so an alert actually fires, hit only the
    first showtime, and never touch saved state."""
    test_cfg = {
        **cfg,
        "bookable_types": sorted(set(cfg.get("bookable_types", ["CanReserve"]))
                                 | {"Wheelchair", "Companion"}),
        "showtimes": cfg["showtimes"][:1],
    }
    label = test_cfg["showtimes"][0]["label"] if test_cfg["showtimes"] else "?"
    print(f"[TEST] Widened seat types, checking only: {label}")
    print("[TEST] If any seats are open there, your phone should buzz. State not saved.")
    check_all(test_cfg, {}, session, save=False)
    print("[TEST] Done. If nothing fired, that showtime has no open seats at all "
          "right now — try another as the first entry, or check the NTFY_TOPIC.")


def main():
    test = "--test" in sys.argv
    cfg = load_json(CONFIG_PATH, None)
    if cfg is None:
        sys.exit("config.json not found — copy config.example.json and fill it in.")
    session = requests.Session()

    if test:
        run_test(cfg, session)
        return

    state = load_json(STATE_PATH, {})
    poll = cfg.get("poll_seconds", 60)
    deadline = time.time() + cfg.get("run_duration_seconds", 270)
    while True:
        check_all(cfg, state, session)
        if time.time() + poll >= deadline:
            break
        time.sleep(poll + random.uniform(-5, 5))


if __name__ == "__main__":
    main()
