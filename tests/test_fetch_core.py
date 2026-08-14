"""Fetching and parsing a Seat Page.

Expected values are read off the real recorded page (showtime 144696966, The Odyssey,
AMC Metreon 16, IMAX 70mm, 2026-08-09 17:00 UTC) rather than recomputed the way the
parser computes them.
"""

from datetime import datetime, timezone

import pytest

from amc_watch.fetch_core import (
    AccessBlocked,
    QueueWalled,
    RateLimited,
    SeatPageShapeChanged,
    SeatPageUnavailable,
    ShowtimeNotFound,
    fetch_seat_page,
)

from .conftest import QUEUE_URL, FakeResponse, FakeSession, Redirect, responding, serving


def test_a_bare_showtime_id_yields_the_whole_showtime(as_recorded):
    """The Seat Page is self-describing — no human ever supplies Showtime metadata."""
    page = fetch_seat_page(144696966, session=as_recorded)

    assert page.showtime_id == 144696966
    assert (page.movie_id, page.movie_name) == (76238, "The Odyssey")
    assert (page.theatre_id, page.theatre_name) == (2325, "AMC Metreon 16")
    assert (page.format_code, page.format_name) == ("imax70mm", "IMAX 70MM")
    assert page.starts_at_utc == datetime(2026, 8, 9, 17, 0, tzinfo=timezone.utc)


def test_seats_carry_grid_coordinates_and_printed_names(as_recorded):
    """Grid coords drive adjacency later; printed names are what Seat Criteria use."""
    page = fetch_seat_page(144696966, session=as_recorded)
    by_name = {s.name: s for s in page.seats}

    assert len(page.seats) == 437
    k10 = by_name["K10"]
    assert (k10.row_letter, k10.number) == ("K", 10)
    assert (k10.grid_row, k10.grid_col) == (10, 25)
    assert k10.seat_type == "CanReserve"


def test_seat_numbers_run_opposite_to_grid_columns(as_recorded):
    """In this house K34 sits at grid column 1 and K1 at column 34.

    Printed seat numbers descend as grid columns ascend, so adjacency can only ever be
    computed from grid coordinates — two seats with consecutive *numbers* are adjacent
    here by coincidence of this layout, not by rule.
    """
    page = fetch_seat_page(144696966, session=as_recorded)
    row_k = {s.number: s.grid_col for s in page.seats if s.row_letter == "K"}

    assert row_k[34] == 1
    assert row_k[1] == 34


def test_the_auditorium_is_missing_row_i(as_recorded):
    """AMC skips row "I". Criteria spanning H-N must not invent seats that don't exist."""
    page = fetch_seat_page(144696966, session=as_recorded)
    letters = sorted({s.row_letter for s in page.seats})

    assert letters == list("ABCDEFGHJKLMN")
    assert "I" not in letters


def test_aisles_are_not_seats(as_recorded):
    """NotASeat cells are dropped, but their grid columns still separate the seats."""
    page = fetch_seat_page(144696966, session=as_recorded)

    assert all(s.seat_type != "NotASeat" for s in page.seats)
    assert all(s.name for s in page.seats)


def test_available_wheelchair_seats_are_not_bookable():
    """The false-alert trap: AMC marks wheelchair/companion seats available too.

    This fixture has every wheelchair and companion seat open and every standard seat
    sold, so a system that trusted `available` would page a user about seats they cannot
    book (CONTEXT.md, "Bookable").
    """
    page = fetch_seat_page(144696966, session=serving("metreon_imax70mm_wheelchair_only"))
    open_seats = [s for s in page.seats if s.available]

    assert {s.seat_type for s in open_seats} == {"Wheelchair", "Companion"}
    assert page.bookable_seats == ()


def test_a_sold_out_house_is_a_successful_fetch():
    """No seats is an answer, not a failure — it must never raise."""
    page = fetch_seat_page(144696966, session=serving("metreon_imax70mm_sold_out"))

    assert page.seats  # the layout is still fully described
    assert page.bookable_seats == ()


def test_an_open_block_reports_its_bookable_seats():
    """Five standard seats open mid-house, contiguous in the grid."""
    page = fetch_seat_page(144696966, session=serving("metreon_imax70mm_open_block"))
    block = sorted(page.bookable_seats, key=lambda s: s.grid_col)

    assert {s.name for s in block} == {"K10", "K11", "K12", "K13", "K14"}
    assert {s.grid_row for s in block} == {10}
    assert [s.grid_col for s in block] == [21, 22, 23, 24, 25]


def test_queue_wall_is_distinct_from_no_seats():
    """A queue redirect answers 200, so status alone would read it as an empty house."""
    session = FakeSession(
        lambda url: FakeResponse(
            text="<html>waiting room</html>",
            url=QUEUE_URL,
            history=[Redirect(QUEUE_URL)],
        )
    )

    with pytest.raises(QueueWalled) as e:
        fetch_seat_page(144696966, session=session)
    assert e.value.showtime_id == 144696966


@pytest.mark.parametrize(
    "status,expected",
    [
        (403, AccessBlocked),
        (404, ShowtimeNotFound),
        (429, RateLimited),
        (500, SeatPageUnavailable),
    ],
)
def test_http_failures_surface_as_distinct_errors(status, expected):
    """An operator must be able to tell a blocked box from a dead showtime ID."""
    with pytest.raises(expected):
        fetch_seat_page(144696966, session=responding(status_code=status))


def test_rate_limiting_is_our_fault_not_amcs():
    """429 says we overspent the Polling Budget: back off, don't retry harder.

    Observed for real on 2026-07-28 after a handful of manual probes, which is how
    little headroom there is.
    """
    with pytest.raises(RateLimited) as e:
        fetch_seat_page(144696966, session=responding(status_code=429))

    assert not isinstance(e.value, AccessBlocked)  # a door, not a speed limit


def test_a_page_without_a_seating_layout_is_loudest():
    """If AMC changes shape, every Watch goes blind — never report that as "no seats"."""
    with pytest.raises(SeatPageShapeChanged):
        fetch_seat_page(144696966, session=responding(text="<html>hello</html>"))


def test_a_transport_failure_is_reported_as_unavailable():
    import requests

    def boom(url):
        raise requests.ConnectionError("connection reset")

    with pytest.raises(SeatPageUnavailable):
        fetch_seat_page(144696966, session=FakeSession(boom))


def test_the_fetch_presents_itself_as_a_browser(as_recorded):
    """Transport behavior is load-bearing against Cloudflare (ADR-0003)."""
    fetch_seat_page(144696966, session=as_recorded)
    sent = as_recorded.requests[0]

    assert sent["url"] == "https://www.amctheatres.com/showtimes/144696966/seats"
    assert "Mozilla/5.0" in sent["headers"]["User-Agent"]
    assert sent["timeout"] == 25
