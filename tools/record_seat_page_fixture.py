"""Record a real Seat Page into test fixtures, and derive the edited variants.

Fixtures must stay *recorded*, not invented: the RSC payload is AMC's shape, not ours,
and a hand-written fixture would only ever prove that our parser matches our imagination.
So this records one real page verbatim and derives every variant from it by flipping
`available` flags in place — the recording stays byte-identical everywhere else.

    # record from a live showtime (residential IP recommended, see ADR-0004)
    python tools/record_seat_page_fixture.py --showtime-id 144696966

    # re-derive variants from an already-saved raw page, no network
    python tools/record_seat_page_fixture.py --from-file raw.html

Only the two RSC script chunks that carry `seatingLayout` and `showDateTimeUtc` are kept
(~68 KB of a ~3.3 MB page); the rest is Next.js bundle noise with no bearing on parsing.
"""

import argparse
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from amc_watch.fetch_core import HEADERS, parse_seat_page, seat_page_url  # noqa: E402

FIXTURE_DIR = Path(__file__).resolve().parent.parent / "tests" / "fixtures" / "rsc"
CHUNK_OPEN = "<script>self.__next_f.push("
CHUNK_CLOSE = "</script>"

# One seat object inside the *escaped* RSC text. Matching escaped rather than decoding and
# re-encoding keeps every untouched byte exactly as AMC sent it.
SEAT_RE = re.compile(
    r'\{\\"available\\":(?P<avail>true|false),'
    r'\\"column\\":(?P<col>\d+),'
    r'\\"row\\":(?P<row>\d+),'
    r'\\"name\\":\\"(?P<name>[^\\]*)\\",'
    r'\\"type\\":\\"(?P<type>[^\\]*)\\"'
)


def fetch_raw(showtime_id):
    import requests

    with requests.Session() as s:
        r = s.get(seat_page_url(showtime_id), headers=HEADERS, timeout=25)
    if "queue.amctheatres.com" in r.url:
        sys.exit("Queue-walled — retry, or record from a residential IP (ADR-0004).")
    r.raise_for_status()
    return r.text


def slice_chunks(html):
    """Keep only the RSC chunks holding the layout and the showtime metadata."""
    out = []
    for key in ('\\"seatingLayout\\"', '\\"showDateTimeUtc\\"'):
        at = html.find(key)
        if at == -1:
            sys.exit(f"{key} not present — page shape changed, or this is not a Seat Page.")
        start = html.rfind(CHUNK_OPEN, 0, at)
        end = html.find(CHUNK_CLOSE, at)
        chunk = html[start : end + len(CHUNK_CLOSE)]
        if chunk not in out:
            out.append(chunk)
    return "".join(out)


def set_availability(text, decide):
    """Rewrite each seat's `available` flag via decide(name, type, current) -> bool."""
    def sub(m):
        want = decide(m["name"], m["type"], m["avail"] == "true")
        return m.group(0).replace(
            f'\\"available\\":{m["avail"]}', f'\\"available\\":{str(want).lower()}'
        )

    return SEAT_RE.sub(sub, text)


def _open_block(name, seat_type, _current):
    """Open a contiguous block of standard seats in row K, leaving the rest sold.

    Row K is mid-house and all-CanReserve in the recording, so the block is unambiguous:
    any Opening found here came from bookable seats, not from the wheelchair/companion
    pair that the sold-out house leaves available.
    """
    if seat_type != "CanReserve":
        return False
    m = re.match(r"^([A-Z]+)(\d+)$", name or "")
    return bool(m and m.group(1) == "K" and 10 <= int(m.group(2)) <= 14)


VARIANTS = {
    # The recording as fetched: a near-sold-out house whose only *available* seats are
    # wheelchair/companion plus a single stray standard seat. Row "I" is absent because
    # AMC skips it — the missing-row case is real here, not synthesized.
    "metreon_imax70mm_as_recorded": None,
    # Nothing at all available: proves an empty result is a successful fetch.
    "metreon_imax70mm_sold_out": lambda n, t, c: False,
    # Only wheelchair/companion available: the false-alert trap. Availability alone is
    # not bookability (CONTEXT.md, "Bookable").
    "metreon_imax70mm_wheelchair_only": lambda n, t, c: t in ("Wheelchair", "Companion"),
    # A five-wide block of standard seats in row K.
    "metreon_imax70mm_open_block": _open_block,
}


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    src = ap.add_mutually_exclusive_group(required=True)
    src.add_argument("--showtime-id", help="fetch this showtime live from AMC")
    src.add_argument("--from-file", type=Path, help="re-derive from a saved raw page")
    args = ap.parse_args()

    html = args.from_file.read_text() if args.from_file else fetch_raw(args.showtime_id)
    base = slice_chunks(html)
    FIXTURE_DIR.mkdir(parents=True, exist_ok=True)

    for name, decide in VARIANTS.items():
        text = base if decide is None else set_availability(base, decide)
        page = parse_seat_page(text)  # every fixture must parse before it is written
        path = FIXTURE_DIR / f"{name}.rsc.txt"
        path.write_text(text)
        print(
            f"{path.name:44} {len(text):>7} bytes  "
            f"{len(page.seats):>3} seats  {len(page.bookable_seats):>3} bookable"
        )


if __name__ == "__main__":
    main()
