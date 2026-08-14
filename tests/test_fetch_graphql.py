"""The GraphQL backend: discovery + seat reads against graph.amctheatres.com (#15).

Same seam as the RSC suite — the outbound HTTP edge is faked with recorded payloads;
query building, the session-date cookie dance, response classification and payload
walking all run for real inward of it. The seat fixture is *derived* from the recorded
RSC page (the RSC payload embeds the same GraphQL showtime object the server queried),
so the two backends are tested against the same recorded AMC data.
"""

import json
from datetime import date, datetime, timezone
from urllib.parse import quote, unquote

from amc_watch.fetch_core import (
    discover_showtimes,
    enumerate_theatres,
    fetch_seat_page,
    fetch_seat_page_graphql,
)

from .conftest import graphql_paging, graphql_serving, serving

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


def test_theatre_enumeration_pages_through_the_whole_connection():
    """query "AMC" matches every theatre; the client follows endCursor until
    hasNextPage goes false, and a Theatre carries what Discovery targeting and the
    theatre pickers need — above all the slug."""
    session = graphql_paging({None: "theatres_page1", "cGM6MToxOjI=": "theatres_page2"})
    theatres = enumerate_theatres(session=session)

    assert [t.theatre_id for t in theatres] == [6, 24, 25]
    esquire = theatres[0]
    assert esquire.slug == "amc-esquire-7"
    assert esquire.name == "AMC Esquire 7"
    assert (esquire.city, esquire.state) == ("Saint Louis", "Missouri")
    assert (esquire.latitude, esquire.longitude) == (38.6485, -90.305)
    assert esquire.ticketable is True

    assert len(session.posts) == 2
    assert session.posts[0]["json"]["variables"]["after"] is None
    assert session.posts[1]["json"]["variables"]["after"] == "cGM6MToxOjI="


def test_discovery_drives_the_business_date_through_the_session_cookie():
    """The target date is cookie-driven, not a query argument (ADR-0005): AMC reads it
    from the session cookie's nowInDays/lastViewedDate. 2026-08-15 is day 20,680 of
    the Unix epoch — worked out by hand, not with the code under test."""
    session = graphql_serving("metreon_discovery")
    discover_showtimes(METREON, business_date=SATURDAY, session=session)

    patched = json.loads(unquote(session.cookies.get("session")))
    assert patched["nowInDays"] == 20680
    assert patched["lastViewedDate"] == "20260815T12:00:00.000Z"
    [set_call] = session.cookies.set_calls
    assert set_call["domain"] == ".amctheatres.com"


def test_the_session_cookies_other_fields_survive_the_date_patch():
    """The warmed cookie is what authorizes the host — the patch must not lobotomize it."""
    warmed = quote(json.dumps({"nowInDays": 20000, "deviceId": "abc-123"}))
    session = graphql_serving("metreon_discovery", cookies={"session": warmed})
    discover_showtimes(METREON, business_date=SATURDAY, session=session)

    patched = json.loads(unquote(session.cookies.get("session")))
    assert patched["deviceId"] == "abc-123"
    assert patched["nowInDays"] == 20680


def test_a_theatre_with_no_showtimes_is_an_answer_not_a_failure():
    """A quiet day must never look like a broken fetch — empty is a valid discovery."""
    rows = discover_showtimes(
        METREON, business_date=SATURDAY, session=graphql_serving("empty_discovery")
    )

    assert rows == ()
