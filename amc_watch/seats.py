"""Fetch an AMC seat page and reduce it to the adjacent free-seat pairs we care about.

The seat page https://www.amctheatres.com/showtimes/<id>/seats is server-rendered: its
Next.js RSC payload embeds a `seatingLayout` object listing every seat with its grid
coordinates, printed name ("N7"), availability, and type. No API key or cookies needed —
a plain HTTP GET with a browser User-Agent returns the whole layout.

Adjacency falls out of the grid: two seats are physically next to each other when they
share a `row` and sit in consecutive `column`s. Aisles are `NotASeat` cells and
wheelchair/companion seats occupy their own column, so both break adjacency for free.
"""

import json
import re
from collections import defaultdict

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
    """Return list of frozenset({nameA, nameB}) for adjacent free seats in the block.

    Only `bookable_types` (default: CanReserve) count — this excludes Wheelchair and
    Companion seats, which show as available but aren't standard seats. A companion/
    wheelchair seat between two reservable seats occupies a grid column, so it also
    correctly breaks adjacency.
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
    """Fetch one showtime's seat page and return its adjacent free-seat pairs."""
    resp = session.get(SEATS_URL.format(id=showtime_id), headers=HEADERS, timeout=25)
    resp.raise_for_status()
    layout = extract_layout(resp.text)
    if layout is None:
        raise ValueError("seatingLayout not found (page shape changed or blocked)")
    return find_adjacent_pairs(parse_seats(layout), cfg)
