"""The Registry: Contribution, enrichment, and querying what is covered.

The pass under test here is the one the poller will call in #4, so it is driven directly
and synchronously — no loops, no sleeps. Exactly one thing is faked: `session.get`. The
recorded Seat Page is parsed for real, which is what makes "no human supplies Showtime
metadata" (ADR-0001) a claim these tests can actually check.
"""

from datetime import datetime, timezone

from amc_watch.registry import contribute, enrich_pending, list_showtimes

from .conftest import (
    QUEUE_URL,
    FakeResponse,
    FakeSession,
    Redirect,
    responding,
    serving,
    serving_each,
)

# Two Showtimes that differ in every way a Watch selector cares about.
TWO_HOUSES = {
    144696966: "metreon_imax70mm_as_recorded",  # The Odyssey, IMAX 70MM, Metreon 16
    145377422: "kabuki_unrecordedformat_edited",  # Avengers Doomsday, Kabuki 8
}


def test_a_contributed_bare_id_fills_itself_in_from_its_seat_page(db_session, as_recorded):
    """The whole point of the Registry: a bare number becomes a described Showtime."""
    contribute(db_session, ["144696966"])

    enrich_pending(db_session, session=as_recorded)

    (showtime,) = list_showtimes(db_session)
    assert showtime.movie_name == "The Odyssey"
    assert showtime.theatre_name == "AMC Metreon 16"
    assert (showtime.format_code, showtime.format_name) == ("imax70mm", "IMAX 70MM")
    assert showtime.starts_at_utc == datetime(2026, 8, 9, 17, 0, tzinfo=timezone.utc)
    assert showtime.layout is not None


def test_re_contributing_a_known_id_is_a_duplicate_rather_than_a_second_row(db_session):
    """Several friends harvesting the same AMC page has to be harmless."""
    first = contribute(db_session, ["144696966"])
    again = contribute(db_session, ["144696966"])

    assert [(o.showtime_id, o.status) for o in first] == [(144696966, "new")]
    assert [(o.showtime_id, o.status) for o in again] == [(144696966, "duplicate")]
    assert len(list_showtimes(db_session)) == 1


def test_a_pasted_seat_page_url_contributes_the_showtime_it_points_at(db_session):
    """What a user actually has on their clipboard is the URL, not the number in it."""
    (outcome,) = contribute(db_session, ["https://www.amctheatres.com/showtimes/144696966/seats"])

    assert (outcome.showtime_id, outcome.status) == (144696966, "new")

    duplicate = contribute(db_session, ["144696966"])
    assert duplicate[0].status == "duplicate"


def test_a_token_that_is_not_a_showtime_is_reported_and_does_not_stop_the_rest(db_session):
    """A typo in a pasted batch must neither vanish nor cost the batch its good IDs."""
    outcomes = contribute(db_session, ["oops", "144696966", "https://example.com/nope"])

    assert [o.status for o in outcomes] == ["invalid", "new", "invalid"]
    assert [o.given for o in outcomes if o.status == "invalid"] == [
        "oops",
        "https://example.com/nope",
    ]
    assert [s.showtime_id for s in list_showtimes(db_session)] == [144696966]


def test_a_dead_showtime_id_is_reported_and_never_costs_another_fetch(db_session):
    """A 404 is permanent, and Polling Budget is the scarce resource — so ask once."""
    contribute(db_session, ["999999999"])
    amc = responding(status_code=404)

    (outcome,) = enrich_pending(db_session, session=amc)
    assert (outcome.showtime_id, outcome.status) == (999999999, "dead")
    assert "404" in outcome.detail

    spent = len(amc.requests)
    assert enrich_pending(db_session, session=amc) == []
    assert len(amc.requests) == spent


def test_re_contributing_a_dead_id_repeats_why_it_is_dead(db_session):
    """The reason has to outlive the pass that found it, or the typo goes quiet again."""
    contribute(db_session, ["999999999"])
    enrich_pending(db_session, session=responding(status_code=404))

    (outcome,) = contribute(db_session, ["999999999"])

    assert outcome.status == "dead"
    assert "404" in outcome.detail


def test_a_queue_walled_fetch_leaves_the_showtime_for_the_next_pass(db_session, as_recorded):
    """"AMC would not talk to us" and "that showtime is not real" must never look alike."""
    contribute(db_session, ["144696966"])
    walled = FakeSession(
        lambda url: FakeResponse(text="waiting room", url=QUEUE_URL, history=[Redirect(QUEUE_URL)])
    )

    (outcome,) = enrich_pending(db_session, session=walled)
    assert outcome.status == "queued"
    assert "queue" in outcome.detail.lower()

    (retried,) = enrich_pending(db_session, session=as_recorded)
    assert retried.status == "enriched"
    assert list_showtimes(db_session)[0].movie_name == "The Odyssey"


def test_a_format_nobody_has_recorded_yet_is_stored_exactly_as_reported(db_session):
    """InfinityVision's code is unknown until the first Doomsday Contribution reveals it.

    So the fixture reports a format deliberately absent from this codebase: if anything
    ever normalises, maps or hardcodes format codes, this is the test that catches it.
    """
    contribute(db_session, ["145377422"])

    enrich_pending(db_session, session=serving("kabuki_unrecordedformat_edited"))

    (showtime,) = list_showtimes(db_session)
    assert showtime.format_code == "formatnobodyhasrecordedyet"
    assert showtime.format_name == "Format Nobody Has Recorded Yet"


def test_the_registry_is_filterable_by_movie_theatre_and_format(db_session):
    """The three axes a Watch selector matches on, so a user can see what is covered."""
    contribute(db_session, [str(i) for i in TWO_HOUSES])
    enrich_pending(db_session, session=serving_each(TWO_HOUSES))

    def ids(**filters):
        return [s.showtime_id for s in list_showtimes(db_session, **filters)]

    assert ids() == [144696966, 145377422]
    assert ids(movie="doomsday") == [145377422]
    assert ids(theatre="metreon") == [144696966]
    assert ids(format="imax70mm") == [144696966]
    assert ids(movie="doomsday", theatre="metreon") == []
