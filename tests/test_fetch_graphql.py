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

import pytest

from amc_watch.fetch_core import (
    AccessBlocked,
    DiscoveryIncomplete,
    FetchUnavailable,
    QueueWalled,
    RateLimited,
    ShapeChanged,
    ShowtimeNotFound,
    TheatreNotFound,
    discover_showtimes,
    enumerate_theatres,
    fetch_seat_page,
    fetch_seat_page_graphql,
)

from .conftest import (
    QUEUE_URL,
    FakeGraphQLResponse,
    FakeGraphQLSession,
    graphql_paging,
    graphql_responding,
    graphql_serving,
    serving,
)

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
    assert odyssey.auditorium == 15  # AMC types auditorium as a bare Int
    assert odyssey.is_reserved_seating is True
    assert (odyssey.theatre_id, odyssey.theatre_slug, odyssey.theatre_name) == (
        2325,
        METREON,
        "AMC Metreon 16",
    )
    assert len(session.posts) == 1  # pre-enriched: one query, no follow-up fetches


def test_the_format_is_the_showtimes_own_format_group_attribute():
    """Live rows answer `format: null` and carry a *mixed* attribute list — Features,
    Amenities and Accessibility sit beside the formats. Only AMC's own "Format" group
    counts, most specific first by its `sort`, so an IMAX 70MM row never reports the
    recliner it also has."""
    rows = discover_showtimes(
        METREON, business_date=SATURDAY, session=graphql_serving("metreon_discovery")
    )
    odyssey = next(r for r in rows if r.showtime_id == 145377422)

    assert (odyssey.format_code, odyssey.format_name) == ("imax70mm", "IMAX 70MM")


def test_a_showtime_with_no_format_attribute_reports_no_format():
    """An ordinary 2D screening has no Format-group attribute at all. Reporting the
    first attribute AMC happens to list would write "reservedseating" into the
    Registry as a format; the honest answer is that there is no format."""
    rows = discover_showtimes(
        METREON, business_date=SATURDAY, session=graphql_serving("ordinary_2d_discovery")
    )

    assert [r.format_code for r in rows] == [""]
    assert rows[0].movie_name == "The Brink of War"  # a real row, not an error


def test_the_seat_read_takes_its_format_from_the_attribute_groups_too():
    """Recorded live from AMC (showtime 145377417): format is null and the identity
    rides the attribute connection, where imax70mm(8) leads reservedseating(170)."""
    page = fetch_seat_page_graphql(
        145377417, session=graphql_serving("showtime_145377417_seats_recorded")
    )

    assert (page.format_code, page.format_name) == ("imax70mm", "IMAX 70MM")
    assert (page.movie_name, page.theatre_name) == ("The Odyssey", "AMC Metreon 16")
    assert len(page.seats) == 437


def test_a_truncated_discovery_is_never_mistaken_for_a_short_day():
    """Discovery is the only door into the Registry: a capped connection with more
    pages means Showtimes nobody will ever watch, and that must be louder than a
    quiet answer."""
    session = graphql_serving("truncated_discovery")

    with pytest.raises(DiscoveryIncomplete) as e:
        discover_showtimes(METREON, business_date=SATURDAY, session=session)
    assert "page size" in str(e.value)


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


@pytest.mark.parametrize(
    "status,expected",
    [
        (403, AccessBlocked),
        (429, RateLimited),
        (500, FetchUnavailable),
    ],
)
def test_graphql_http_failures_surface_as_distinct_errors(status, expected):
    """A blocked box, an overspent Polling Budget and a flaky host each need their own
    operator remedy — on this surface exactly as on the RSC one."""
    with pytest.raises(expected):
        fetch_seat_page_graphql(145377422, session=graphql_responding(status_code=status))


def test_a_queue_redirect_on_the_graphql_host_is_named_for_what_it_is():
    """The graph host is not queue-walled today (ADR-0005) — if AMC ever claps it
    behind Queue-it, that must surface by name, not as a mystery parse failure."""
    session = graphql_responding(text="<html>waiting room</html>", url=QUEUE_URL)

    with pytest.raises(QueueWalled):
        discover_showtimes(METREON, business_date=SATURDAY, session=session)


def test_a_non_json_answer_is_a_shape_change():
    """A challenge interstitial answering 200 must never read as an empty discovery."""
    session = graphql_responding(text="<html>prove you are human</html>")

    with pytest.raises(ShapeChanged):
        discover_showtimes(METREON, business_date=SATURDAY, session=session)


def test_graphql_level_errors_are_loud_and_carry_amcs_words():
    """A top-level `errors` array means the query no longer fits the schema — the
    loudest failure, and the message should quote AMC so the operator can read it."""
    session = FakeGraphQLSession(
        lambda posted: FakeGraphQLResponse(
            payload={"errors": [{"message": "Cannot query field 'showtimes'"}]}
        )
    )

    with pytest.raises(ShapeChanged) as e:
        discover_showtimes(METREON, business_date=SATURDAY, session=session)
    assert "Cannot query field 'showtimes'" in str(e.value)


def test_a_400_carrying_graphql_errors_quotes_amc_not_just_the_status():
    """GraphQL servers put validation errors in the body of a 400 — observed live
    2026-08-14, where the bare status hid "Cannot query field ...". The operator
    must get AMC's words, and a schema rejection is a shape change, not downtime."""
    session = FakeGraphQLSession(
        lambda posted: FakeGraphQLResponse(
            status_code=400,
            payload={"errors": [{"message": 'Cannot query field "edges" on type "X"'}]},
        )
    )

    with pytest.raises(ShapeChanged) as e:
        discover_showtimes(METREON, business_date=SATURDAY, session=session)
    assert 'Cannot query field "edges"' in str(e.value)


def test_a_null_showtime_is_a_dead_id_not_a_shape_change():
    """GraphQL answering `showtime: null` is AMC saying "no such showtime" — the
    404-equivalent, distinct from the payload changing shape."""
    session = FakeGraphQLSession(
        lambda posted: FakeGraphQLResponse(payload={"data": {"viewer": {"showtime": None}}})
    )

    with pytest.raises(ShowtimeNotFound) as e:
        fetch_seat_page_graphql(999999999, session=session)
    assert e.value.showtime_id == 999999999


def test_a_null_theatre_is_a_dead_slug_not_a_quiet_day():
    """A wrong slug is stale config an operator must hear about; it must never look
    like a theatre with nothing scheduled."""
    session = FakeGraphQLSession(
        lambda posted: FakeGraphQLResponse(payload={"data": {"viewer": {"theatre": None}}})
    )

    with pytest.raises(TheatreNotFound):
        discover_showtimes("amc-nowhere-0", business_date=SATURDAY, session=session)


def test_a_graphql_transport_failure_is_reported_as_unavailable():
    def boom(posted):
        raise ConnectionError("connection reset")

    with pytest.raises(FetchUnavailable):
        discover_showtimes(METREON, business_date=SATURDAY, session=FakeGraphQLSession(boom))


def test_a_missing_schema_field_is_a_shape_change_not_a_dead_id():
    """`showtime: null` means the ID is dead; the *field* vanishing means AMC moved
    the schema and every Watch is blind. The CLI prints a different remedy for each,
    so conflating them sends the operator to swap IDs forever."""
    session = FakeGraphQLSession(
        lambda posted: FakeGraphQLResponse(payload={"data": {"viewer": {}}})
    )

    with pytest.raises(ShapeChanged):
        fetch_seat_page_graphql(145377422, session=session)


def test_a_missing_theatre_field_is_a_shape_change_not_a_dead_slug():
    session = FakeGraphQLSession(
        lambda posted: FakeGraphQLResponse(payload={"data": {"viewer": {}}})
    )

    with pytest.raises(ShapeChanged):
        discover_showtimes(METREON, business_date=SATURDAY, session=session)


@pytest.mark.parametrize(
    "errors",
    [
        {"message": "a bare object, not a list"},
        ["a bare string"],
        [{"message": "well formed"}],
    ],
)
def test_any_shape_of_graphql_errors_still_lands_in_the_taxonomy(errors):
    """This branch runs when the response is least trustworthy, so the formatter
    itself must not be the thing that crashes."""
    session = FakeGraphQLSession(
        lambda posted: FakeGraphQLResponse(status_code=400, payload={"errors": errors})
    )

    with pytest.raises(ShapeChanged):
        discover_showtimes(METREON, business_date=SATURDAY, session=session)


def test_a_shape_change_carries_the_showtime_id_it_was_reading():
    """The ID is what an operator needs to reproduce the loudest failure class, and
    the shared extractors do not know it."""
    payload = {
        "data": {"viewer": {"showtime": {
            "showtimeId": 145377422,
            "showDateTimeUtc": "2026-08-15T17:00:00.000Z",
            "format": {"attributes": [{"code": "imax70mm", "name": "IMAX 70MM"}]},
            "movie": {"name": "The Odyssey"},  # movieId gone
            "theatre": {"theatreId": 2325, "name": "AMC Metreon 16"},
            "seatingLayout": {"seats": [
                {"name": "K10", "row": 10, "column": 25, "available": True, "type": "CanReserve"}
            ]},
        }}}
    }
    session = FakeGraphQLSession(lambda posted: FakeGraphQLResponse(payload=payload))

    with pytest.raises(ShapeChanged) as e:
        fetch_seat_page_graphql(145377422, session=session)
    assert e.value.showtime_id == 145377422


def test_an_unreadable_id_is_a_shape_change_not_a_value_error():
    """A schema change to a string-formatted ID passes the missing-field check; it
    must still land in the taxonomy every caller catches on."""
    payload = {"data": {"viewer": {"theatres": {
        "pageInfo": {"hasNextPage": False, "endCursor": None},
        "edges": [{"node": {"theatreId": "two thousand", "slug": "amc-metreon-16"}}],
    }}}}
    session = FakeGraphQLSession(lambda posted: FakeGraphQLResponse(payload=payload))

    with pytest.raises(ShapeChanged):
        enumerate_theatres(session=session)


def test_theatre_paging_refuses_to_walk_a_cursor_that_never_advances():
    """A repeating cursor would POST the same page forever — the surest way to turn a
    polite client into a blocked one."""
    page = {"data": {"viewer": {"theatres": {
        "pageInfo": {"hasNextPage": True, "endCursor": "stuck"},
        "edges": [{"node": {"theatreId": 6, "slug": "amc-esquire-7", "name": "AMC Esquire 7"}}],
    }}}}
    session = FakeGraphQLSession(lambda posted: FakeGraphQLResponse(payload=page))

    with pytest.raises(ShapeChanged) as e:
        enumerate_theatres(session=session)
    assert "not advancing" in str(e.value)
    assert len(session.posts) < 5  # it stopped, rather than hammering AMC


def test_the_date_patch_leaves_exactly_one_session_cookie():
    """The jar keys on (domain, name): setting ours beside the warm-up's host-only
    cookie would put two `session` values on the wire and let AMC choose the date."""
    session = graphql_serving("metreon_discovery", cookies={"session": quote('{"nowInDays": 1}')})
    discover_showtimes(METREON, business_date=SATURDAY, session=session)

    [(domain, value)] = session.cookies.entries("session")
    assert domain == ".amctheatres.com"
    assert json.loads(unquote(value))["nowInDays"] == 20680


def test_the_graphql_post_presents_itself_as_the_browser_would():
    """The browser's ordinary cross-origin headers — cookies + Origin/Referer, never a
    vendor key or custom header — are what authorize the call (ADR-0005)."""
    session = graphql_serving("metreon_imax70mm_seats")
    fetch_seat_page_graphql(144696966, session=session)
    [sent] = session.posts

    assert sent["url"] == "https://graph.amctheatres.com/"
    assert sent["headers"]["Origin"] == "https://www.amctheatres.com"
    assert sent["headers"]["Accept"] == "application/json"
    assert "X-AMC-Vendor-Key" not in sent["headers"]
    assert sent["timeout"] == 25
    assert "seatingLayout" in sent["json"]["query"]
