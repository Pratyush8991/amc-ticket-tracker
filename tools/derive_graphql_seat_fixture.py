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
from pathlib import Path

REPO = Path(__file__).parent.parent
SOURCE = REPO / "tests" / "fixtures" / "rsc" / "metreon_imax70mm_as_recorded.rsc.txt"
TARGET = REPO / "tests" / "fixtures" / "graphql" / "metreon_imax70mm_seats.json"


def _unescape(html):
    return html.replace('\\"', '"').replace("\\\\", "\\")


def _enclosing_object_start(text, at):
    depth = 0
    for i in range(at - 1, -1, -1):
        c = text[i]
        if c == "}":
            depth += 1
        elif c == "{":
            if depth == 0:
                return i
            depth -= 1
    raise SystemExit("no enclosing object found")


def _object_around(text, anchor):
    at = text.find(anchor)
    if at == -1:
        raise SystemExit(f"{anchor} not found in the RSC fixture")
    obj, _ = json.JSONDecoder().raw_decode(text, _enclosing_object_start(text, at))
    return obj


def _object_after(text, anchor):
    at = text.find(anchor)
    if at == -1:
        raise SystemExit(f"{anchor} not found in the RSC fixture")
    obj, _ = json.JSONDecoder().raw_decode(text, text.find("{", at + len(anchor)))
    return obj


def main():
    text = _unescape(SOURCE.read_text())
    showtime = _object_around(text, '"showDateTimeUtc"')
    layout = _object_after(text, '"seatingLayout"')

    # Live (2026-08-14), viewer.showtime answers `format: null`; the format identity
    # rides the AttributeConnection instead, format attribute first — exactly the
    # `attributes` edges the RSC embed also carries, which is what we copy here.
    attribute_edges = [
        {"node": {"code": e["node"]["code"], "name": e["node"]["name"]}}
        for e in (showtime.get("attributes") or {}).get("edges") or []
    ]

    response = {
        "data": {
            "viewer": {
                "showtime": {
                    "showtimeId": showtime["showtimeId"],
                    "showDateTimeUtc": showtime["showDateTimeUtc"],
                    "format": None,
                    "attributes": {"edges": attribute_edges},
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
