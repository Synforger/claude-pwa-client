"""Tickets written outside every boundary before the guard judged the tickets: those that may not stay there move to the
place the guard gives for the tab that opened them, once, when the backend starts."""
from __future__ import annotations

from backend.tests.async_run import run
from backend.tests.tickets.samples import ticket_env  # noqa: F401
from backend.tickets import ticket_file, ticket_index, ticket_places, ticket_relocate, ticket_service

SECRET = "a line copied from inside a boundary"


def _boundary(env) -> str:
    (env.root / "company").mkdir(exist_ok=True)
    return str(env.root / "company" / "tickets")


def _unjudged_ticket(text: str = SECRET, *, operator_said: bool = False) -> str:
    """A ticket opened while no judgement of the tickets was configured (= it sits outside every boundary)."""
    return run(ticket_service.open_ticket("ses_a", "Title", text, operator_said=operator_said))["id"]


def _judge(env, place: str, *, place_answer: dict | None = None, refuse_at: dict | None = None) -> None:
    env.guard.use("place", "write", place=place_answer or {"stdout": place},
                  write={"refuse_at": refuse_at if refuse_at is not None else {str(env.tickets): SECRET}})


def test_a_ticket_that_may_not_stay_outside_moves_to_its_openers_place_with_every_line(ticket_env):
    ticket = _unjudged_ticket()
    before = ticket_file.path_of(ticket_env.tickets, ticket).read_text()
    place = _boundary(ticket_env)
    _judge(ticket_env, place)
    outcomes = run(ticket_relocate.relocate_outside_tickets())
    assert outcomes[ticket].startswith("moved")
    assert not ticket_file.path_of(ticket_env.tickets, ticket).exists()
    assert ticket_file.path_of(ticket_env.root / "company" / "tickets", ticket).read_text() == before
    key = ticket_index.get(ticket).place_key
    assert key == ticket_places.key_of(ticket_env.root / "company" / "tickets")
    assert run(ticket_places.folder_for(key)) == ticket_env.root / "company" / "tickets"


def test_the_ticket_is_judged_by_its_lines_as_written_with_the_writers_names(ticket_env):
    ticket = _unjudged_ticket("nothing secret")
    place = _boundary(ticket_env)
    _judge(ticket_env, place, refuse_at={str(ticket_env.tickets): "client work"})   # = the opening tab's name
    assert run(ticket_relocate.relocate_outside_tickets())[ticket].startswith("moved")


def test_a_ticket_that_may_stay_outside_stays(ticket_env):
    ticket = _unjudged_ticket("nothing secret")
    _judge(ticket_env, _boundary(ticket_env))
    assert run(ticket_relocate.relocate_outside_tickets()) == {ticket: "fits"}
    assert ticket_file.path_of(ticket_env.tickets, ticket).exists()
    assert ticket_index.get(ticket).place_key == ticket_places.outside_key()


def test_a_ticket_whose_opener_has_no_place_inside_a_boundary_stays_and_is_named(ticket_env, caplog):
    ticket = _unjudged_ticket()
    _judge(ticket_env, str(ticket_env.tickets))
    assert run(ticket_relocate.relocate_outside_tickets())[ticket].startswith("stays")
    assert ticket_file.path_of(ticket_env.tickets, ticket).exists()
    assert ticket in caplog.text


def test_a_ticket_the_guard_cannot_place_stays(ticket_env):
    ticket = _unjudged_ticket()
    _judge(ticket_env, "", place_answer={"status": 1, "stderr": "two boundaries"})
    assert run(ticket_relocate.relocate_outside_tickets())[ticket].startswith("stays")


def test_a_ticket_that_does_not_fit_its_openers_place_either_stays(ticket_env):
    ticket = _unjudged_ticket()
    place = _boundary(ticket_env)
    _judge(ticket_env, place, refuse_at={str(ticket_env.tickets): SECRET, place: SECRET})
    assert run(ticket_relocate.relocate_outside_tickets())[ticket].startswith("stays")
    assert ticket_file.path_of(ticket_env.tickets, ticket).exists()


def test_the_place_is_asked_with_the_tab_where_the_operator_typed_the_quoted_words(ticket_env):
    _unjudged_ticket(operator_said=True)
    _judge(ticket_env, _boundary(ticket_env))
    run(ticket_relocate.relocate_outside_tickets())
    assert ticket_env.guard.calls("place")[-1]["flags"] == {"--place-for": "conv-ses_a", "--typed-in": "conv-ses_a"}


def test_nothing_is_judged_or_moved_without_the_place_and_write_judgements(ticket_env):
    ticket = _unjudged_ticket()
    ticket_env.guard.use("write", write={"refuse_at": {str(ticket_env.tickets): SECRET}})
    assert run(ticket_relocate.relocate_outside_tickets()) == {}
    assert ticket_file.path_of(ticket_env.tickets, ticket).exists()


def test_a_ticket_already_inside_a_boundary_is_not_judged(ticket_env):
    place = _boundary(ticket_env)
    ticket_env.guard.use("place", place={"stdout": place})
    ticket = _unjudged_ticket()
    _judge(ticket_env, place)
    assert ticket not in run(ticket_relocate.relocate_outside_tickets())
