"""The GraphQL backend: discovery + seat reads against graph.amctheatres.com (#15).

Same seam as the RSC suite — the outbound HTTP edge is faked with recorded payloads;
query building, the session-date cookie dance, response classification and payload
walking all run for real inward of it. The seat fixture is *derived* from the recorded
RSC page (the RSC payload embeds the same GraphQL showtime object the server queried),
so the two backends are tested against the same recorded AMC data.
"""

from amc_watch.fetch_core import fetch_seat_page, fetch_seat_page_graphql

from .conftest import graphql_serving, serving


def test_the_graphql_seat_read_yields_the_same_seat_page_as_the_rsc_parser():
    """The RSC fetcher can back-stop seat reads only because both backends land on
    the identical value object — one SeatPage, whichever surface answered."""
    gql = fetch_seat_page_graphql(144696966, session=graphql_serving("metreon_imax70mm_seats"))
    rsc = fetch_seat_page(144696966, session=serving("metreon_imax70mm_as_recorded"))

    assert gql == rsc
    assert gql.showtime_id == 144696966
    assert (gql.format_code, gql.format_name) == ("imax70mm", "IMAX 70MM")
    assert len(gql.seats) == 437
