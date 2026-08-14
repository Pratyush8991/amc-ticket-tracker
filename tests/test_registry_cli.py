"""The Registry from an operator's keyboard.

Contribution is UI-less until #9, so this CLI is how showtime IDs actually get into the
Registry while Doomsday seats are selling. Tests drive `main()` exactly as a shell would
and read what it printed — the database and the parser are real, only `session.get` is
faked.
"""

from amc_watch.cli import main

from .conftest import QUEUE_URL, FakeResponse, FakeSession, Redirect, responding, serving_each
from .test_registry import TWO_HOUSES

CONTRIBUTED = "144696966"


def columns(out):
    """The printed report as rows of words, so column widths stay free to change."""
    return [line.split() for line in out.strip().splitlines() if line.strip()]


def test_contribute_reports_every_id_it_was_given(db_session, capsys):
    exit_code = main(["contribute", CONTRIBUTED, CONTRIBUTED], db=db_session)

    assert exit_code == 0
    reported = columns(capsys.readouterr().out)
    assert [row[:2] for row in reported] == [
        [CONTRIBUTED, "new"],
        [CONTRIBUTED, "duplicate"],
    ]


def test_a_pasted_url_is_reported_as_the_showtime_it_resolved_to(db_session, capsys):
    """The report is a list of showtimes, so a 60-character URL must not be the label."""
    main(["contribute", f"https://www.amctheatres.com/showtimes/{CONTRIBUTED}/seats"], db=db_session)

    assert columns(capsys.readouterr().out)[0][:2] == [CONTRIBUTED, "new"]


def test_contribute_can_enrich_in_the_same_breath(db_session, capsys, as_recorded):
    """The demo: hand it a bare number, watch the row describe itself back."""
    exit_code = main(["contribute", CONTRIBUTED, "--enrich"], db=db_session, session=as_recorded)

    assert exit_code == 0
    out = capsys.readouterr().out
    assert [row[1] for row in columns(out)] == ["new", "enriched"]
    # Nobody typed any of this: it came off the Seat Page.
    assert "The Odyssey" in out
    assert "imax70mm" in out


def test_enrich_is_a_pass_over_whatever_is_pending(db_session, capsys, as_recorded):
    """Contribution is network-free; this is the command that spends the fetch."""
    main(["contribute", CONTRIBUTED], db=db_session)
    capsys.readouterr()

    assert main(["enrich"], db=db_session, session=as_recorded) == 0
    out = capsys.readouterr().out
    assert [row[1] for row in columns(out)] == ["enriched"]
    assert "The Odyssey" in out

    assert main(["enrich"], db=db_session, session=as_recorded) == 0
    assert "nothing pending" in capsys.readouterr().out


def test_the_registry_lists_what_is_covered_and_filters_it(db_session, capsys):
    """"What is already covered?" is the question that stops duplicate ID-hunting."""
    both = [str(showtime_id) for showtime_id in TWO_HOUSES]
    main(["contribute", *both, "--enrich"], db=db_session, session=serving_each(TWO_HOUSES))
    capsys.readouterr()

    assert main(["registry"], db=db_session) == 0
    everything = capsys.readouterr().out
    assert "The Odyssey" in everything
    assert "Avengers Doomsday" in everything

    assert main(["registry", "--movie", "doomsday"], db=db_session) == 0
    by_movie = capsys.readouterr().out
    assert "Avengers Doomsday" in by_movie
    assert "The Odyssey" not in by_movie

    assert main(["registry", "--theatre", "metreon"], db=db_session) == 0
    by_theatre = capsys.readouterr().out
    assert "AMC Metreon 16" in by_theatre
    assert "AMC Kabuki 8" not in by_theatre

    assert main(["registry", "--format", "imax70mm"], db=db_session) == 0
    by_format = capsys.readouterr().out
    assert "IMAX 70MM" in by_format
    assert "Avengers Doomsday" not in by_format


def test_the_registry_shows_rows_that_are_still_waiting_to_be_enriched(db_session, capsys):
    """A contributed ID is in the Registry the moment it is contributed, described or not."""
    main(["contribute", CONTRIBUTED], db=db_session)
    capsys.readouterr()

    assert main(["registry"], db=db_session) == 0
    out = capsys.readouterr().out
    assert CONTRIBUTED in out
    assert "pending" in out


def test_an_unreachable_database_is_reported_the_way_a_blocked_box_is(capsys, monkeypatch):
    """An operator who just SSH'd in gets a remedy, not a SQLAlchemy stack trace."""
    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://localhost:1/nowhere")

    exit_code = main(["contribute", CONTRIBUTED])

    assert exit_code != 0
    out = capsys.readouterr().out
    assert "FAIL" in out
    assert "DATABASE_URL" in out
    assert "Traceback" not in out


def test_a_typo_makes_contribute_exit_non_zero_without_losing_the_good_id(db_session, capsys):
    """Exit code is the only part of this a script reads, so a swallowed typo is silence."""
    exit_code = main(["contribute", "oops", CONTRIBUTED], db=db_session)

    assert exit_code != 0
    out = capsys.readouterr().out
    assert "oops" in out
    assert "invalid" in out

    main(["registry"], db=db_session)
    assert CONTRIBUTED in capsys.readouterr().out


def test_an_id_amc_would_not_enrich_makes_enrich_exit_non_zero(db_session, capsys):
    """Both walls count: a dead showtime and a box that never got an answer."""
    main(["contribute", "999999999"], db=db_session)
    capsys.readouterr()

    exit_code = main(["enrich"], db=db_session, session=responding(status_code=404))
    assert exit_code != 0
    assert "dead" in capsys.readouterr().out

    main(["contribute", CONTRIBUTED], db=db_session)
    capsys.readouterr()
    walled = FakeSession(
        lambda url: FakeResponse(text="waiting room", url=QUEUE_URL, history=[Redirect(QUEUE_URL)])
    )
    assert main(["enrich"], db=db_session, session=walled) != 0
    assert "queued" in capsys.readouterr().out
