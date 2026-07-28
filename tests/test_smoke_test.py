"""The operator smoke test — the first act on any new box (ADR-0004).

Its whole job is to answer one question before anything is built on a machine: can this
box reach a Seat Page at all? So the exit code has to be trustworthy and the reason has
to be readable by someone who just SSH'd in.
"""

import pytest

from amc_watch.cli import main

from .conftest import QUEUE_URL, FakeResponse, FakeSession, Redirect, responding, serving


def test_a_reachable_seat_page_passes(capsys):
    exit_code = main(["smoke-test"], session=serving("metreon_imax70mm_as_recorded"))
    out = capsys.readouterr().out

    assert exit_code == 0
    assert "PASS" in out
    # Proves it parsed, not merely that something answered 200.
    assert "The Odyssey" in out
    assert "imax70mm" in out


def test_a_sold_out_house_still_passes(capsys):
    """The smoke test asks "can we see the page", not "are there seats"."""
    exit_code = main(["smoke-test"], session=serving("metreon_imax70mm_sold_out"))

    assert exit_code == 0
    assert "PASS" in capsys.readouterr().out


def test_a_queue_walled_box_fails_and_says_so(capsys):
    session = FakeSession(
        lambda url: FakeResponse(text="waiting room", url=QUEUE_URL, history=[Redirect(QUEUE_URL)])
    )

    exit_code = main(["smoke-test"], session=session)
    out = capsys.readouterr().out

    assert exit_code != 0
    assert "FAIL" in out
    assert "queue" in out.lower()


def test_a_blocked_box_names_the_datacenter_ip_contingency(capsys):
    """A 403 from a fresh cloud box is the ADR-0004 fallback trigger; say that out loud."""
    exit_code = main(["smoke-test"], session=responding(status_code=403))
    out = capsys.readouterr().out

    assert exit_code != 0
    assert "FAIL" in out
    assert "403" in out


def test_a_shape_change_is_reported_as_a_shape_change(capsys):
    exit_code = main(["smoke-test"], session=responding(text="<html>nothing here</html>"))
    out = capsys.readouterr().out

    assert exit_code != 0
    assert "FAIL" in out
    assert "seatingLayout" in out or "shape" in out.lower()


def test_the_showtime_id_can_be_overridden(capsys):
    """Default IDs rot as showtimes pass, so an operator must be able to supply one."""
    session = serving("metreon_imax70mm_as_recorded")
    exit_code = main(["smoke-test", "--showtime-id", "144696969"], session=session)

    assert exit_code == 0
    assert session.requests[0]["url"].endswith("/showtimes/144696969/seats")


@pytest.mark.live
def test_smoke_test_against_real_amc(capsys):
    """Deselected by default (-m 'not live'); this is the one that hits AMC for real."""
    exit_code = main(["smoke-test"])
    assert exit_code == 0, capsys.readouterr().out
