"""Derive the GraphQL seat-query fixture from the recorded RSC Seat Page.

The RSC payload *embeds* the GraphQL showtime object (the Next.js server ran the same
query we now send directly), so the GraphQL fixture is built from the same recorded AMC
data rather than invented — which is what lets the test suite assert that the GraphQL
seat read and the RSC parse yield the *identical* SeatPage (issue #15, AC "same SeatPage
shape as the RSC parser").

Usage:  python tools/derive_graphql_seat_fixture.py
Writes: tests/fixtures/graphql/metreon_imax70mm_seats.json
"""

import json
import sys
from pathlib import Path

REPO = Path(__file__).parent.parent
sys.path.insert(0, str(REPO / "src"))

# The unescaping and object-walking rules are the parser's, not this tool's: importing
# them keeps a fixture derived under the same rules the parser reads it back with.
from amc_watch.fetch_core.parse import (  # noqa: E402
    _enclosing_object_start,
    unescape_payload,
)

SOURCE = REPO / "tests" / "fixtures" / "rsc" / "metreon_imax70mm_as_recorded.rsc.txt"
TARGET = REPO / "tests" / "fixtures" / "graphql" / "metreon_imax70mm_seats.json"


def _object_around(text, anchor):
    at = text.find(anchor)
    if at == -1:
        raise SystemExit(f"{anchor} not found in the RSC fixture")
    start = _enclosing_object_start(text, at, "fixture derivation")
    obj, _ = json.JSONDecoder().raw_decode(text, start)
    return obj


def _object_after(text, anchor):
    at = text.find(anchor)
    if at == -1:
        raise SystemExit(f"{anchor} not found in the RSC fixture")
    obj, _ = json.JSONDecoder().raw_decode(text, text.find("{", at + len(anchor)))
    return obj


def main():
    text = unescape_payload(SOURCE.read_text())
    showtime = _object_around(text, '"showDateTimeUtc"')
    layout = _object_after(text, '"seatingLayout"')

    # The RSC embed types `format` as a Relay connection; the schema we query types it
    # as ShowtimeMovieFormat with a plain `attributes` list, so the format AMC reported
    # for this showtime is re-shaped (not invented) into the type our query asks for.
    # The RSC embed carries no attribute *groups*, so this fixture cannot stand in for
    # the live `format: null` shape — tests/fixtures/graphql/*_recorded.json, taken from
    # the live endpoint by tools/record_graphql_fixtures.py, covers that.
    format_attributes = [
        {"code": e["node"]["code"], "name": e["node"]["name"]}
        for e in (showtime.get("format") or {}).get("edges") or []
    ]

    response = {
        "data": {
            "viewer": {
                "showtime": {
                    "showtimeId": showtime["showtimeId"],
                    "showDateTimeUtc": showtime["showDateTimeUtc"],
                    "format": {"attributes": format_attributes},
                    "movie": {
                        "movieId": showtime["movie"]["movieId"],
                        "name": showtime["movie"]["name"],
                    },
                    "theatre": {
                        "theatreId": showtime["theatre"]["theatreId"],
                        "name": showtime["theatre"]["name"],
                    },
                    "seatingLayout": layout,
                }
            }
        }
    }
    TARGET.parent.mkdir(parents=True, exist_ok=True)
    TARGET.write_text(json.dumps(response, indent=1) + "\n")
    print(f"wrote {TARGET.relative_to(REPO)} ({TARGET.stat().st_size} bytes)")


if __name__ == "__main__":
    main()
