"""The guard's five commands as the tickets use them: 0, 1, 2 and no key, for the place, the write, the covers and the read."""
from __future__ import annotations

import pytest
from fastapi import HTTPException

from backend._common import paths
from backend.tests.async_run import run
from backend.tests.tickets.samples import ticket_env  # noqa: F401
from backend.terminal.tab_memo import tier_folder
from backend.tickets import ticket_checks, ticket_entry, ticket_file, ticket_index, ticket_places, ticket_service
from backend.tickets.ticket_entry import Writer


def _code(coroutine) -> str:
    with pytest.raises(HTTPException) as refused:
        run(coroutine)
    return refused.value.detail["code"]


def _boundary(env, name="company") -> str:
    """A boundary's `tickets/` folder whose parent is there, as the guard names it."""
    (env.root / name).mkdir(exist_ok=True)
    return str(env.root / name / "tickets")


def _open(operator_said=False, tab="ses_a"):
    return run(ticket_service.open_ticket(tab, "Title", "Request", operator_said=operator_said))


# --- where a ticket is kept -------------------------------------------------------------------------------------------


def test_without_the_place_command_the_place_is_the_one_outside_every_boundary(ticket_env):
    assert run(ticket_checks.decide_place("ses_a")) == paths.TICKETS_DIR


def test_the_folder_the_guard_prints_is_the_place_as_it_is_with_nothing_added(ticket_env):
    folder = _boundary(ticket_env)
    ticket_env.guard.use("place", place={"stdout": folder})
    answer = _open()
    assert answer["place_outside"] is False
    assert (ticket_env.root / "company" / "tickets" / f"{answer['id']}.jsonl").is_file()
    assert not (ticket_env.root / "company" / "tickets" / "tickets").exists()
    assert not (ticket_env.tickets / f"{answer['id']}.jsonl").exists()


def test_the_guard_is_told_the_opening_tabs_session_and_the_flag_for_the_operators_session_only_when_there_is_one(ticket_env):
    ticket_env.guard.use("place", place={"stdout": str(ticket_env.tickets)})
    _open()
    _open(operator_said=True)
    flags = [call["flags"] for call in ticket_env.guard.calls("place")]
    assert flags == [{"--place-for": "conv-ses_a"}, {"--place-for": "conv-ses_a", "--typed-in": "conv-ses_a"}]


def test_a_place_that_does_not_fit_one_folder_opens_nothing_and_says_to_cross_the_boundary(ticket_env):
    ticket_env.guard.use("place", place={"status": 1, "stderr": "two boundaries"})
    assert _code(ticket_service.open_ticket("ses_a", "t", "x", operator_said=False)) == "ticket_place_split"
    assert ticket_index.rows() == {}


@pytest.mark.parametrize("answer", [{"status": 2}, {"status": 5}, {"status": 0, "stdout": ""},
                                    {"status": 0, "stdout": "relative/folder"}])
def test_any_other_answer_is_an_unknown_place_and_opens_nothing(ticket_env, answer):
    ticket_env.guard.use("place", place=answer)
    assert _code(ticket_service.open_ticket("ses_a", "t", "x", operator_said=False)) == "ticket_place_unknown"
    assert ticket_index.rows() == {}


def test_a_place_whose_parent_folder_is_not_there_opens_nothing(ticket_env):
    ticket_env.guard.use("place", place={"stdout": str(ticket_env.root / "nowhere" / "tickets")})
    assert _code(ticket_service.open_ticket("ses_a", "t", "x", operator_said=False)) == "ticket_place_unknown"


def test_the_place_command_that_cannot_run_is_an_unknown_place(ticket_env):
    from backend.tests.tickets.samples import write_config  # noqa: PLC0415
    write_config(ticket_env.guard._monkeypatch, ticket_env.root, ticket_place_check=["/no/such/program"])
    assert _code(ticket_service.open_ticket("ses_a", "t", "x", operator_said=False)) == "ticket_place_unknown"


# --- what is written ----------------------------------------------------------------------------------------------------


def test_a_text_the_write_check_lets_through_is_added_and_the_check_saw_the_place_and_the_text(ticket_env):
    ticket = _open()["id"]
    ticket_env.guard.use("write")
    run(ticket_service.add("ses_b", ticket, "all fine"))
    call = ticket_env.guard.calls("write")[-1]
    assert call["text"] == "all fine" and call["flags"]["--to-place"] == str(ticket_env.tickets)
    assert "--typed-in" not in call["flags"]


def test_a_text_the_write_check_refuses_is_not_added_and_the_reason_comes_back(ticket_env):
    ticket = _open()["id"]
    ticket_env.guard.use("write", write={"refuse_containing": "SECRET", "stderr": "that is protected"})
    before = ticket_file.read(ticket_env.tickets, ticket)
    with pytest.raises(HTTPException) as refused:
        run(ticket_service.add("ses_b", ticket, "the SECRET plan"))
    assert (refused.value.detail["code"], refused.value.detail["params"]["reason"]) == ("ticket_refused", "that is protected")
    assert ticket_file.read(ticket_env.tickets, ticket) == before


@pytest.mark.parametrize("status", [2, 3])
def test_a_write_check_that_cannot_judge_stops_the_write(ticket_env, status):
    ticket = _open()["id"]
    ticket_env.guard.use("write", write={"status": status})
    assert _code(ticket_service.add("ses_b", ticket, "x")) == "ticket_check_failed"
    assert len(ticket_file.read(ticket_env.tickets, ticket)) == 1


def test_without_the_write_key_nothing_is_judged(ticket_env):
    ticket = _open()["id"]
    run(ticket_service.add("ses_b", ticket, "x"))
    assert ticket_env.guard.calls() == []


def test_the_first_lines_are_judged_before_the_ticket_is_made_the_title_with_the_request_and_the_operator_words_apart(ticket_env):
    ticket_env.guard.use("write", write={"refuse_containing": "please fix"})
    assert _code(ticket_service.open_ticket("ses_a", "T", "request", operator_said=True)) == "ticket_refused"
    assert ticket_index.rows() == {}
    texts = [(call["text"], call["flags"].get("--typed-in")) for call in ticket_env.guard.calls("write")]
    assert texts == [("T\n\nrequest", "conv-ses_a"), ("please fix the title", "conv-ses_a")]


def test_a_close_without_a_last_word_and_a_pass_have_nothing_to_judge(ticket_env):
    ticket = _open()["id"]
    ticket_env.guard.use("write", write={"status": 2})
    run(ticket_service.close("ses_a", ticket, ""))
    assert ticket_env.guard.calls("write") == []


# --- who may take part ------------------------------------------------------------------------------------------------


def test_a_tab_that_has_not_read_the_boundary_cannot_add_ask_or_close(ticket_env):
    ticket = _open()["id"]
    ticket_env.guard.use("covers", covers={"refuse_sessions": ["conv-ses_b"]})
    for change in (ticket_service.add("ses_b", ticket, "x"), ticket_service.ask("ses_b", ticket, "mac", "x", None),
                   ticket_service.close("ses_b", ticket, "")):
        assert _code(change) == "ticket_outside_place"
    assert [entry["kind"] for entry in ticket_file.read(ticket_env.tickets, ticket)] == ["opened"]
    run(ticket_service.add("ses_c", ticket, "this one may"))
    flags = ticket_env.guard.calls("covers")[0]["flags"]
    assert flags == {"--to": "conv-ses_b", "--covers-place": str(ticket_env.tickets), "--folder": str(tier_folder("ses_b"))}


def test_a_covers_check_that_cannot_run_is_a_failed_check_not_an_outside_place(ticket_env):
    from backend.tests.tickets.samples import write_config  # noqa: PLC0415
    ticket = _open()["id"]
    write_config(ticket_env.guard._monkeypatch, ticket_env.root, ticket_covers_check=["/no/such/program"])
    assert _code(ticket_service.add("ses_b", ticket, "x")) == "ticket_check_failed"


# --- what is read -------------------------------------------------------------------------------------------------------


def test_a_line_the_reader_may_not_read_is_replaced_and_the_others_are_shown(ticket_env):
    ticket = _open()["id"]
    run(ticket_service.add("ses_b", ticket, "a line from another boundary"))
    run(ticket_service.add("ses_b", ticket, "a plain line"))
    ticket_env.guard.use("read", read={"refuse_containing": "another boundary"})
    shown = run(ticket_service.show("ses_c", ticket))["entries"]
    assert [entry.get("text") for entry in shown] == ["Request", ticket_entry.HIDDEN_TEXT, "a plain line"]
    assert shown[1] == {"kind": "added", "at": shown[1]["at"], "hidden": True, "text": ticket_entry.HIDDEN_TEXT}
    assert all(call["flags"]["--to"] == "conv-ses_c" for call in ticket_env.guard.calls("read"))


def test_the_title_is_judged_as_part_of_the_first_line(ticket_env):
    ticket = run(ticket_service.open_ticket("ses_a", "A title with SECRET", "plain body", operator_said=False))["id"]
    ticket_env.guard.use("read", read={"refuse_containing": "SECRET"})
    shown = run(ticket_service.show("ses_c", ticket))["entries"]
    assert shown == [{"kind": "opened", "at": shown[0]["at"], "hidden": True, "text": ticket_entry.HIDDEN_TEXT}]


@pytest.mark.parametrize("status", [1, 2, 7])
def test_a_read_check_that_does_not_say_yes_shows_nothing_of_the_line(ticket_env, status):
    ticket = _open()["id"]
    ticket_env.guard.use("read", read={"status": status})
    assert run(ticket_service.show("ses_c", ticket))["entries"][0].get("hidden") is True


def test_without_the_read_key_every_line_is_shown(ticket_env):
    ticket = _open()["id"]
    assert run(ticket_service.show("ses_c", ticket))["entries"][0]["text"] == "Request"


def test_the_listing_judges_no_line(ticket_env):
    _open()
    ticket_env.guard.use("read", read={"status": 1})
    assert run(ticket_service.list_tickets())["tickets"][0]["title"] == "Title"
    assert ticket_env.guard.calls() == []


# --- a judgement left out on a machine whose messages the guard judges ------------------------------------------------


def _guarded_without(env, *modes: str) -> None:
    """The guard judges the messages, and of the tickets' judgements only `modes`."""
    env.guard.base = {**env.guard.base, "agent_message_check": ["peers.py", "--to", "{session}"]}
    env.guard.use(*modes, place={"stdout": str(env.tickets)})


def test_a_ticket_is_not_opened_unjudged_where_the_guard_judges_the_messages(ticket_env):
    _guarded_without(ticket_env)
    assert _code(ticket_service.open_ticket("ses_a", "t", "x", operator_said=False)) == "ticket_check_missing"
    assert ticket_index.rows() == {}


def test_a_line_is_not_added_unjudged_where_the_guard_judges_the_messages(ticket_env):
    ticket = _open()["id"]
    _guarded_without(ticket_env, "place", "places", "covers", "read")
    assert _code(ticket_service.add("ses_a", ticket, "more")) == "ticket_check_missing"


def test_a_ticket_is_not_shown_unjudged_where_the_guard_judges_the_messages(ticket_env):
    ticket = _open()["id"]
    _guarded_without(ticket_env, "place", "places", "write", "covers")
    assert _code(ticket_service.show("ses_a", ticket)) == "ticket_check_missing"
