"""The operator smoke test — the first act on any new box (ADR-0004, amended by 0005).

Its whole job is to answer one question before anything is built on a machine: can this
box reach AMC at all — now on *both* surfaces, the RSC Seat Page GET and the GraphQL
host via curl_cffi. So the exit code has to be trustworthy and the reason has to be
readable by someone who just SSH'd in.
"""

import pytest

from amc_watch.cli import main

from .conftest import (
    QUEUE_URL,
    FakeGraphQLResponse,
    FakeResponse,
    FakeSession,
    Redirect,
    graphql_responding,
    graphql_serving,
    responding,
    serving,
)


def healthy_graphql():
    return graphql_serving("metreon_discovery")


def test_a_box_that_reaches_both_surfaces_passes(capsys):
    exit_code = main(
        ["smoke-test"],
        session=serving("metreon_imax70mm_as_recorded"),
        graphql_session=healthy_graphql(),
    )
    out = capsys.readouterr().out

    assert exit_code == 0
    assert out.count("PASS") == 2
    # Proves both parsed, not merely that something answered 200.
    assert "The Odyssey" in out
    assert "imax70mm" in out
    assert "graph.amctheatres.com" in out


def test_a_sold_out_house_still_passes(capsys):
    """The smoke test asks "can we see the page", not "are there seats"."""
    exit_code = main(
        ["smoke-test"],
        session=serving("metreon_imax70mm_sold_out"),
        graphql_session=healthy_graphql(),
    )

    assert exit_code == 0
    assert capsys.readouterr().out.count("PASS") == 2


def test_an_empty_discovery_still_passes(capsys):
    """Reach is the question, not volume — a quiet theatre is a healthy box."""
    exit_code = main(
        ["smoke-test"],
        session=serving("metreon_imax70mm_as_recorded"),
        graphql_session=graphql_serving("empty_discovery"),
    )

    assert exit_code == 0
    assert capsys.readouterr().out.count("PASS") == 2


def test_a_graphql_blocked_box_fails_even_when_the_seat_page_passes(capsys):
    """The surfaces fail independently (ADR-0005): a box is healthy only when both
    answer — discovery being blind is exactly what the smoke test exists to catch."""
    exit_code = main(
        ["smoke-test"],
        session=serving("metreon_imax70mm_as_recorded"),
        graphql_session=graphql_responding(status_code=403),
    )
    out = capsys.readouterr().out

    assert exit_code != 0
    assert "FAIL" in out
    assert "403" in out


def test_a_queue_walled_box_fails_and_says_so(capsys):
    session = FakeSession(
        lambda url: FakeResponse(text="waiting room", url=QUEUE_URL, history=[Redirect(QUEUE_URL)])
    )

    exit_code = main(["smoke-test"], session=session, graphql_session=healthy_graphql())
    out = capsys.readouterr().out

    assert exit_code != 0
    assert "FAIL" in out
    assert "queue" in out.lower()


def test_a_blocked_box_names_the_datacenter_ip_contingency(capsys):
    """A 403 from a fresh cloud box is the ADR-0004 fallback trigger; say that out loud."""
    exit_code = main(
        ["smoke-test"], session=responding(status_code=403), graphql_session=healthy_graphql()
    )
    out = capsys.readouterr().out

    assert exit_code != 0
    assert "FAIL" in out
    assert "403" in out


def test_a_shape_change_is_reported_as_a_shape_change(capsys):
    exit_code = main(
        ["smoke-test"],
        session=responding(text="<html>nothing here</html>"),
        graphql_session=healthy_graphql(),
    )
    out = capsys.readouterr().out

    assert exit_code != 0
    assert "FAIL" in out
    assert "seatingLayout" in out or "shape" in out.lower()


def test_the_showtime_id_can_be_overridden(capsys):
    """Default IDs rot as showtimes pass, so an operator must be able to supply one."""
    session = serving("metreon_imax70mm_as_recorded")
    exit_code = main(
        ["smoke-test", "--showtime-id", "144696969"],
        session=session,
        graphql_session=healthy_graphql(),
    )

    assert exit_code == 0
    assert session.requests[0]["url"].endswith("/showtimes/144696969/seats")


def test_the_theatre_slug_can_be_overridden(capsys):
    """Slugs are far more stable than showtime IDs, but an operator can still point
    the discovery probe somewhere else."""
    graphql_session = healthy_graphql()
    exit_code = main(
        ["smoke-test", "--theatre-slug", "amc-empire-25"],
        session=serving("metreon_imax70mm_as_recorded"),
        graphql_session=graphql_session,
    )

    assert exit_code == 0
    assert graphql_session.posts[0]["json"]["variables"]["slug"] == "amc-empire-25"


class UnreachableWarmup:
    """A curl_cffi session whose warm-up GET fails the way a fresh box's does."""

    def __init__(self, boom=None, status_code=200):
        self.boom = boom
        self.status_code = status_code
        self.closed = False

    def get(self, url, timeout=None):
        if self.boom:
            raise self.boom
        return FakeGraphQLResponse(payload={}, status_code=self.status_code, url=url)

    def close(self):
        self.closed = True


@pytest.fixture
def warmup_session(monkeypatch):
    """Point open_graphql_session's curl_cffi import at a session we control."""

    def install(session):
        import curl_cffi.requests

        monkeypatch.setattr(curl_cffi.requests, "Session", lambda **kw: session)
        return session

    return install


def test_a_box_that_cannot_even_warm_its_cookie_jar_fails_readably(capsys, warmup_session):
    """The likeliest failure on a fresh box, and the whole reason the command exists:
    it must print the remedy, not a traceback out of curl_cffi."""
    session = warmup_session(UnreachableWarmup(boom=OSError("connection reset")))

    exit_code = main(
        ["smoke-test"], session=serving("metreon_imax70mm_as_recorded"), graphql_session=None
    )
    out = capsys.readouterr().out

    assert exit_code != 0
    assert "FAIL" in out
    assert "connection reset" in out
    assert session.closed  # the half-built session is not leaked


def test_a_warm_up_that_is_refused_names_the_datacenter_contingency(capsys, warmup_session):
    """A 403 warming the jar is the same door-in-the-face as a 403 at the graph host,
    and earns the same ADR-0004 remedy rather than a confusing downstream error."""
    warmup_session(UnreachableWarmup(status_code=403))

    exit_code = main(
        ["smoke-test"], session=serving("metreon_imax70mm_as_recorded"), graphql_session=None
    )
    out = capsys.readouterr().out

    assert exit_code != 0
    assert "403" in out
    assert "re-home the poller" in out


@pytest.mark.live
def test_smoke_test_against_real_amc(capsys):
    """Deselected by default (-m 'not live'); this is the one that hits AMC for real —
    both surfaces, including the curl_cffi reach at graph.amctheatres.com."""
    exit_code = main(["smoke-test"])
    assert exit_code == 0, capsys.readouterr().out
