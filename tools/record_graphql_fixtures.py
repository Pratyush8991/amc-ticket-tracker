"""Record live GraphQL responses as test fixtures.

The suite must run against payloads AMC actually sends, not payloads we imagined —
this is what caught `format: null` and the attribute-group discriminator. Recording is
a deliberate, manual act: it spends Polling Budget on the host that 429s easily, so it
takes one showtime and one theatre per run and writes exactly what came back.

Usage:  python tools/record_graphql_fixtures.py --showtime-id <id> [--theatre-slug <slug>]
Writes: tests/fixtures/graphql/<name>_recorded.json
"""

import argparse
import json
import sys
from datetime import date
from pathlib import Path

REPO = Path(__file__).parent.parent
sys.path.insert(0, str(REPO / "src"))

from amc_watch.fetch_core.graphql.client import (  # noqa: E402
    _graphql,
    _patch_business_date,
    graphql_session,
)
from amc_watch.fetch_core.graphql.queries import DISCOVERY_QUERY, seat_query  # noqa: E402

FIXTURES = REPO / "tests" / "fixtures" / "graphql"


def _write(name, payload):
    FIXTURES.mkdir(parents=True, exist_ok=True)
    target = FIXTURES / f"{name}.json"
    target.write_text(json.dumps(payload, indent=1) + "\n")
    print(f"wrote {target.relative_to(REPO)} ({target.stat().st_size} bytes)")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--showtime-id", type=int, help="record this showtime's seat read")
    parser.add_argument("--theatre-slug", help="record this theatre's discovery pass")
    parser.add_argument("--timeout", type=int, default=25)
    args = parser.parse_args(argv)
    if not args.showtime_id and not args.theatre_slug:
        parser.error("give --showtime-id, --theatre-slug, or both")

    with graphql_session(timeout=args.timeout) as session:
        if args.showtime_id:
            payload = _graphql(
                session,
                seat_query(args.showtime_id),
                args.timeout,
                showtime_id=args.showtime_id,
            )
            _write(f"showtime_{args.showtime_id}_seats_recorded", payload)
        if args.theatre_slug:
            _patch_business_date(session, date.today())
            payload = _graphql(
                session,
                DISCOVERY_QUERY,
                args.timeout,
                variables={"slug": args.theatre_slug},
            )
            _write(f"{args.theatre_slug.replace('-', '_')}_discovery_recorded", payload)
    return 0


if __name__ == "__main__":
    sys.exit(main())
