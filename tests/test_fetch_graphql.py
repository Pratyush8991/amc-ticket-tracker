"""The GraphQL backend: discovery + seat reads against graph.amctheatres.com (#15).

Same seam as the RSC suite — the outbound HTTP edge is faked with recorded payloads;
query building, the session-date cookie dance, response classification and payload
walking all run for real inward of it. The seat fixture is *derived* from the recorded
RSC page (the RSC payload embeds the same GraphQL showtime object the server queried),
so the two backends are tested against the same recorded AMC data.
"""

from datetime import date, datetime, timezone

from amc_watch.fetch_core import discover_showtimes, fetch_seat_page, fetch_seat_page_graphql

from .conftest import graphql_serving, serving

METREON = "amc-metreon-16"
SATURDAY = date(2026, 8, 15)


def test_the_graphql_seat_read_yields_the_same_seat_page_as_the_rsc_parser():
    """The RSC fetcher can back-stop seat reads only because both backends land on
    the identical value object — one SeatPage, whichever surface answered."""
    gql = fetch_seat_page_graphql(144696966, session=graphql_serving("metreon_imax70mm_seats"))
    rsc = fetch_seat_page(144696966, session=serving("metreon_imax70mm_as_recorded"))

    assert gql == rsc
    assert gql.showtime_id == 144696966
    assert (gql.format_code, gql.format_name) == ("imax70mm", "IMAX 70MM")
    assert len(gql.seats) == 437


def test_discovery_returns_pre_enriched_showtimes_with_no_second_fetch():
    """Discovery rows arrive whole — movie, format, start time, auditorium, theatre —
    so no human labels a showtime and no enrichment fetch follows (CONTEXT.md)."""
    session = graphql_serving("metreon_discovery")
    rows = discover_showtimes(METREON, business_date=SATURDAY, session=session)
    by_id = {r.showtime_id: r for r in rows}

    odyssey = by_id[145377422]
    assert (odyssey.movie_id, odyssey.movie_name) == (76238, "The Odyssey")
    assert odyssey.movie_slug == "the-odyssey"
    assert (odyssey.format_code, odyssey.format_name) == ("imax70mm", "IMAX 70MM")
    assert odyssey.starts_at_utc == datetime(2026, 8, 15, 17, 0, tzinfo=timezone.utc)
    assert odyssey.auditorium == "House 15"
    assert odyssey.is_reserved_seating is True
    assert (odyssey.theatre_id, odyssey.theatre_slug, odyssey.theatre_name) == (
        2325,
        METREON,
        "AMC Metreon 16",
    )
    assert len(session.posts) == 1  # pre-enriched: one query, no follow-up fetches


def test_discovery_unions_across_format_tabs_and_groups_deduped_by_id():
    """The same Showtime listed under two format tabs is one Showtime; separate groups
    within a tab all contribute rows."""
    rows = discover_showtimes(
        METREON, business_date=SATURDAY, session=graphql_serving("metreon_discovery")
    )

    assert [r.showtime_id for r in rows] == [145377422, 145377423, 145901234]


def test_a_format_code_arrives_from_discovery_never_hardcoded():
    """InfinityVision's code was unknown until AMC reported it — the system stores what
    discovery says, verbatim (parent #1, "Registry enrichment")."""
    rows = discover_showtimes(
        METREON, business_date=SATURDAY, session=graphql_serving("metreon_discovery")
    )
    doomsday = next(r for r in rows if r.movie_name == "Avengers: Doomsday")

    assert (doomsday.format_code, doomsday.format_name) == ("infinityvision", "InfinityVision")
    assert doomsday.status == "OnSale"


def test_a_theatre_with_no_showtimes_is_an_answer_not_a_failure():
    """A quiet day must never look like a broken fetch — empty is a valid discovery."""
    rows = discover_showtimes(
        METREON, business_date=SATURDAY, session=graphql_serving("empty_discovery")
    )

    assert rows == ()
