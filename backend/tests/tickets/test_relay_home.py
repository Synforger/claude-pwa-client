"""The machine that keeps a ticket, receiving the other machine's commands: only a ticket outside every boundary is given,
the other machine's tab is written as `<machine>:<tab>` with no tier, its text is judged as a reader that has read nothing,
the operator's own words never leave, and `pass` is done here whoever the two tabs are."""
from __future__ import annotations

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from backend._common.state import SessionDef
from backend.jsonl.jsonl_predicates import AGENT_MESSAGE_REMOTE_OPENING
from backend.routes import tickets as ticket_routes
from backend.tests.async_run import run
from backend.tests.tickets.samples import PEER_ADDRESS, PEER_URL, asked_at_of, outside_ticket, relay_env  # noqa: F401
from backend.tests.tickets.samples import ticket_env  # noqa: F401
from backend.tickets import ticket_answer, ticket_file, ticket_index, ticket_pass, ticket_service, relay_home

FROM = ("company", "ses_x", "notes")        # the machine, the tab and its name


@pytest.fixture
def home(relay_env):
    """This machine is `home` and keeps the tickets; `company` is the other."""
    relay_env.configure("home", "company")
    return relay_env


@pytest.fixture
def door(home):
    app = FastAPI()
    app.include_router(ticket_routes.router)
    return TestClient(app, client=(PEER_ADDRESS, 50000))


def _error(response) -> tuple[int, str]:
    return response.status_code, response.json()["detail"]["code"]


def _code(coroutine) -> str:
    with pytest.raises(HTTPException) as refused:
        run(coroutine)
    return refused.value.detail["code"]


def _inside_boundary(ticket: str) -> None:
    ticket_index.put(ticket, ticket_index.get(ticket)._replace(place_key="0" * 16))


# --- add and close ---


def test_a_tab_of_the_other_machine_adds_a_line_written_with_its_machine_and_no_tier(home):
    ticket = outside_ticket()
    assert run(relay_home.add("company", ticket, "ses_x", "notes", "I did it")) == {"ok": True, "id": ticket, "status": "open"}
    last = ticket_file.read(home.tickets, ticket)[-1]
    assert (last["kind"], last["tab"], last["tab_title"], last["tier"], last["text"]) == (
        "added", "company:ses_x", "notes @company", "", "I did it")
    assert ticket_index.get(ticket).holder == "ses_a"


def test_a_line_of_the_other_machine_sets_a_ticket_aside_and_a_plain_one_puts_it_back_to_open(home):
    ticket = outside_ticket()
    assert run(relay_home.add("company", ticket, "ses_x", "notes", "waits", waiting=True, due="2026-12-01"))["status"] == "waiting"
    row = ticket_index.get(ticket)
    assert (row.status, row.due) == ("waiting", "2026-12-01")
    assert run(relay_home.add("company", ticket, "ses_x", "notes", "went on"))["status"] == "open"
    assert ticket_index.get(ticket).due == "2026-12-01"


def test_the_list_for_the_other_machine_gives_the_origin_and_the_due_day(home):
    ticket = outside_ticket()
    ticket_index.put(ticket, ticket_index.get(ticket)._replace(origin="operator", due="2026-12-01"))
    [item] = run(relay_home.list_tickets("company"))["tickets"]
    assert (item["origin"], item["due"]) == ("operator", "2026-12-01")


def test_the_added_text_is_judged_as_a_reader_that_has_read_no_boundary_and_a_refusal_writes_nothing(home):
    ticket = outside_ticket()
    home.guard.use("write", write={"refuse_containing": "secret"})
    assert _code(relay_home.add("company", ticket, "ses_x", "notes", "a secret")) == "ticket_refused"
    assert [entry["kind"] for entry in ticket_file.read(home.tickets, ticket)] == ["opened"]
    [call] = home.guard.calls("write")
    assert call["flags"]["--to-place"] == str(home.tickets) and call["flags"].get("--typed-in") in (None, "")


def test_a_ticket_inside_a_boundary_takes_nothing_from_the_other_machine(home):
    ticket = outside_ticket()
    _inside_boundary(ticket)
    assert _code(relay_home.add("company", ticket, "ses_x", "notes", "x")) == "ticket_inside_boundary"
    assert _code(relay_home.close("company", ticket, "ses_x", "notes", "x")) == "ticket_inside_boundary"
    assert _code(relay_home.show("company", ticket, "ses_x")) == "ticket_inside_boundary"
    assert _code(ticket_pass.pass_from_peer("company", "ses_x", "notes", ticket, "home", "ses_b")) == "ticket_inside_boundary"


def test_a_closed_ticket_takes_no_line_from_the_other_machine(home):
    ticket = outside_ticket()
    run(ticket_service.close("ses_a", ticket, ""))
    assert _code(relay_home.add("company", ticket, "ses_x", "notes", "x")) == "ticket_closed"


def test_the_other_machine_closes_a_ticket_and_an_empty_last_word_is_not_judged(home):
    ticket = outside_ticket()
    home.guard.use("write", write={"status": 1})
    assert run(relay_home.close("company", ticket, "ses_x", "notes", ""))["status"] == "closed"
    assert home.guard.calls("write") == []
    last = ticket_file.read(home.tickets, ticket)[-1]
    assert (last["kind"], last["tab"], last["tab_title"]) == ("closed", "company:ses_x", "notes @company")


def test_a_last_word_that_leaves_is_judged(home):
    ticket = outside_ticket()
    home.guard.use("write", write={"status": 1})
    assert _code(relay_home.close("company", ticket, "ses_x", "notes", "all done")) == "ticket_refused"
    assert ticket_index.get(ticket).status == "open"


# --- show and list ---


def test_show_gives_no_word_of_the_operator_to_the_other_machine_only_the_kind_and_the_time(home):
    ticket = outside_ticket()
    run(ticket_service.ask("ses_a", ticket, "decide", "A or B?", "A"))
    run(ticket_answer.answer(ticket, asked_at_of(home.tickets, ticket), "Take B", False))
    answer = run(relay_home.show("company", ticket, "ses_x"))
    kinds = [(entry["kind"], entry.get("hidden", False)) for entry in answer["entries"]]
    assert kinds == [("opened", False), ("asked", False), ("answered", True)]
    answered = answer["entries"][-1]
    assert set(answered) == {"kind", "at", "hidden", "text"} and "Take B" not in str(answer)


def test_show_judges_each_line_for_the_reader_as_a_tab_of_the_other_machine(home):
    ticket = outside_ticket()
    run(ticket_service.add("ses_b", ticket, "a secret line"))
    home.guard.use("read", read={"refuse_containing": "secret"})
    answer = run(relay_home.show("company", ticket, "ses_x"))
    assert [entry.get("hidden", False) for entry in answer["entries"]] == [False, True]
    assert {call["flags"]["--to"] for call in home.guard.calls("read")} == {"company:ses_x"}


def test_show_writes_the_tabs_as_the_other_machine_reads_them(home):
    ticket = outside_ticket(holder="ses_b")
    run(relay_home.add("company", ticket, "ses_x", "notes", "x"))
    ticket_index.put(ticket, ticket_index.get(ticket)._replace(holder="company:ses_x"))
    answer = run(relay_home.show("company", ticket, "ses_x"))
    assert (answer["holder"], answer["opener"], answer["home"], answer["place_outside"]) == ("ses_x", "home:ses_a", "home", True)
    assert [entry["tab"] for entry in answer["entries"]] == ["home:ses_a", "ses_x"]


def test_the_list_has_only_the_tickets_outside_every_boundary_and_no_title(home):
    outside, inside = outside_ticket(title="Plain"), outside_ticket(title="Inside title")
    _inside_boundary(inside)
    answer = run(relay_home.list_tickets("company"))
    assert [item["id"] for item in answer["tickets"]] == [outside]
    assert set(answer["tickets"][0]) == {"id", "opened_at", "status", "wants", "holder", "opener", "origin", "due"}
    assert "Plain" not in str(answer) and inside not in str(answer) and "Inside title" not in str(answer)
    assert answer["tickets"][0]["holder"] == "home:ses_a"


# --- pass ---


def test_a_tab_of_the_other_machine_passes_a_ticket_to_a_tab_here_and_is_told_the_way_a_message_from_there_is(home):
    ticket = outside_ticket()
    answer = run(ticket_pass.pass_from_peer("company", "ses_x", "notes", ticket, "home", "slides"))
    assert answer == {"ok": True, "id": ticket, "to": "home:ses_c"}                     # as the other machine reads it
    assert ticket_index.get(ticket).holder == "ses_c"
    [(tab, message)] = home.typed
    first, tag, body, closing = message.split("\n")
    assert tab == "ses_c" and first == AGENT_MESSAGE_REMOTE_OPENING
    assert tag == f'<agent-message from="notes @company" session="company:ses_x" ticket="{ticket}">'
    last = ticket_file.read(home.tickets, ticket)[-1]
    assert (last["kind"], last["tab"], last["tab_title"], last["to"]) == ("passed", "company:ses_x", "notes @company", "ses_c")
    assert home.handed == []            # no child's memo: the sender is not a tab of this machine


def test_a_tab_of_the_other_machine_passes_a_ticket_to_a_tab_of_its_own_and_this_machine_asks_it_to_tell_the_tab(home):
    ticket = outside_ticket()
    home.peer_says["/notify"] = (200, {"ok": True, "to": "ses_far"})
    answer = run(ticket_pass.pass_from_peer("company", "ses_x", "notes", ticket, "company", "far tab"))
    assert answer == {"ok": True, "id": ticket, "to": "ses_far"}
    assert ticket_index.get(ticket).holder == "company:ses_far"
    assert home.typed == []
    [(url, payload)] = home.carried
    assert url == f"{PEER_URL}/agent-messages/tickets/{ticket}/notify"
    assert payload == {"to": "far tab", "from_machine": "company", "from_session": "ses_x", "from_title": "notes"}
    assert ticket_file.read(home.tickets, ticket)[-1]["to"] == "company:ses_far"


def test_a_ticket_is_not_passed_to_a_tab_of_a_third_machine(home):
    ticket = outside_ticket()
    assert _code(ticket_pass.pass_from_peer("company", "ses_x", "notes", ticket, "office", "x")) == "ticket_to_third_machine"
    assert ticket_index.get(ticket).holder == "ses_a" and home.carried == [] and home.typed == []


def test_the_ticket_does_not_move_when_the_other_machine_cannot_tell_the_tab(home):
    ticket = outside_ticket()
    home.peer_says["/notify"] = home.down
    assert _code(ticket_pass.pass_from_peer("company", "ses_x", "notes", ticket, "company", "far")) == "ticket_peer_down"
    assert ticket_index.get(ticket).holder == "ses_a"
    assert [entry["kind"] for entry in ticket_file.read(home.tickets, ticket)] == ["opened"]


def test_the_other_machines_refusal_to_tell_the_tab_leaves_the_ticket_and_comes_back(home):
    ticket = outside_ticket()
    home.peer_says["/notify"] = (409, {"detail": {"code": "agent_message_unknown_receiver", "message": "no such tab"}})
    assert _code(ticket_pass.pass_from_peer("company", "ses_x", "notes", ticket, "company", "far")) == "agent_message_unknown_receiver"
    assert ticket_index.get(ticket).holder == "ses_a"


def test_a_tab_here_passes_a_ticket_to_a_tab_of_the_other_machine(home):
    ticket = outside_ticket()
    home.peer_says["/notify"] = (200, {"ok": True, "to": "ses_far", "kept": True})
    answer = run(ticket_pass.pass_ticket("ses_a", ticket, "company:far tab"))
    assert answer == {"ok": True, "id": ticket, "to": "company:ses_far", "kept": True}
    assert ticket_index.get(ticket).holder == "company:ses_far"
    [(_url, payload)] = home.carried
    assert payload == {"to": "far tab", "from_machine": "home", "from_session": "ses_a", "from_title": "client work"}
    last = ticket_file.read(home.tickets, ticket)[-1]
    assert (last["tab"], last["tab_title"], last["tier"], last["to"]) == ("ses_a", "client work", "projects/AP", "company:ses_far")
    assert home.handed == []


def test_the_text_that_goes_to_the_other_machine_is_judged_and_the_tab_must_be_allowed_to_talk_to_it(home):
    ticket = outside_ticket()
    home.configure("home", "company", accounts=["work"])
    assert _code(ticket_pass.pass_ticket("ses_a", ticket, "company:far")) == "agent_message_peer_not_allowed"
    assert home.carried == []


def test_a_ticket_inside_a_boundary_is_not_passed_to_a_tab_of_the_other_machine_either(home):
    ticket = outside_ticket()
    _inside_boundary(ticket)
    assert _code(ticket_pass.pass_ticket("ses_a", ticket, "company:far")) == "ticket_inside_boundary"
    assert home.carried == []


@pytest.mark.parametrize("setup, code", [("waiting", "ticket_waiting_operator"), ("pending", "ticket_answer_pending")])
def test_a_ticket_waiting_for_the_operator_or_for_its_answer_is_not_passed_from_the_other_machine_either(home, monkeypatch, setup, code):
    from backend.tickets import answer_delivery
    monkeypatch.setattr(answer_delivery, "start_delivery", lambda key: None)
    ticket = outside_ticket()
    run(ticket_service.ask("ses_a", ticket, "decide", "A or B?", "A"))
    if setup == "pending":
        run(ticket_answer.answer(ticket, asked_at_of(home.tickets, ticket), "Take B", False))
    assert _code(ticket_pass.pass_from_peer("company", "ses_x", "notes", ticket, "home", "ses_b")) == code


def test_a_tab_that_passes_a_ticket_to_itself_on_the_other_machine_is_refused(home):
    ticket = outside_ticket()
    assert _code(ticket_pass.pass_from_peer("company", "ses_x", "notes", ticket, "company", "ses_x")) == "ticket_to_self"


# --- the line that tells a tab here ---


def test_the_other_machine_has_this_one_tell_a_tab_by_name_and_gets_the_tabs_id(home):
    answer = run(relay_home.notify("company", {"accounts": None}, "company-261119-01", "slides", "company", "ses_x", "notes"))
    assert answer == {"ok": True, "to": "ses_c"}
    [(tab, message)] = home.typed
    assert tab == "ses_c" and message.startswith(f"{AGENT_MESSAGE_REMOTE_OPENING}\n")
    assert 'ticket="company-261119-01"' in message and "tabs ticket show company-261119-01" in message


def test_a_line_for_a_sender_on_a_third_machine_is_not_typed(home):
    assert _code(relay_home.notify("company", {"accounts": None}, "company-261119-01", "slides", "office", "ses_x", "notes")) == "ticket_to_third_machine"
    assert home.typed == []


def test_a_tab_the_other_machine_may_not_talk_to_is_not_told(home):
    assert _code(relay_home.notify("company", {"accounts": ["work"]}, "company-261119-01", "slides", "company", "ses_x", "notes")) == "agent_message_peer_not_allowed"
    assert home.typed == []


def test_a_name_that_is_no_tab_is_the_message_doors_unknown_receiver(home):
    assert _code(relay_home.notify("company", {"accounts": None}, "company-261119-01", "nobody", "company", "ses_x", "notes")) == "agent_message_unknown_receiver"


# --- the doors ---


def test_the_doors_answer_the_configured_other_machine_only(home):
    app = FastAPI()
    app.include_router(ticket_routes.router)
    ticket = outside_ticket()
    for caller in (TestClient(app, client=("203.0.113.77", 1)), TestClient(app)):
        answers = [caller.post(f"/agent-messages/tickets/{ticket}/entries", json={"from_session": "s", "from_title": "t", "text": "x"}),
                   caller.post(f"/agent-messages/tickets/{ticket}/close", json={"from_session": "s", "from_title": "t", "text": ""}),
                   caller.post(f"/agent-messages/tickets/{ticket}/pass", json={"from_session": "s", "from_title": "t", "to_machine": "home", "to": "x"}),
                   caller.post(f"/agent-messages/tickets/{ticket}/notify", json={"to": "x", "from_machine": "company", "from_session": "s", "from_title": "t"}),
                   caller.get(f"/agent-messages/tickets/{ticket}", params={"reader": "s"}), caller.get("/agent-messages/tickets")]
        assert [_error(answer) for answer in answers] == [(403, "agent_message_unknown_peer")] * 6
    assert [entry["kind"] for entry in ticket_file.read(home.tickets, ticket)] == ["opened"]


def test_the_doors_take_the_other_machines_commands(home, door):
    ticket = outside_ticket()
    assert door.post(f"/agent-messages/tickets/{ticket}/entries",
                     json={"from_session": "ses_x", "from_title": "notes", "text": "hi"}).json() == {"ok": True, "id": ticket, "status": "open"}
    assert door.get(f"/agent-messages/tickets/{ticket}", params={"reader": "ses_x"}).json()["entries"][-1]["text"] == "hi"
    assert [item["id"] for item in door.get("/agent-messages/tickets").json()["tickets"]] == [ticket]
    passed = door.post(f"/agent-messages/tickets/{ticket}/pass",
                       json={"from_session": "ses_x", "from_title": "notes", "to_machine": "home", "to": "ses_b"})
    assert passed.json() == {"ok": True, "id": ticket, "to": "home:ses_b"}
    closed = door.post(f"/agent-messages/tickets/{ticket}/close", json={"from_session": "ses_x", "from_title": "notes", "text": ""})
    assert closed.json()["status"] == "closed"


@pytest.mark.parametrize("body", [{}, {"from_session": "s", "from_title": "t"}, {"from_session": "s", "from_title": "t", "text": 5},
                                  {"from_session": "s", "from_title": "t", "text": "  "}, {"from_session": "", "from_title": "t", "text": "x"}])
def test_a_form_of_the_other_machine_that_cannot_be_read_is_400(home, door, body):
    ticket = outside_ticket()
    assert _error(door.post(f"/agent-messages/tickets/{ticket}/entries", json=body)) == (400, "ticket_bad_relay")


def test_a_ticket_that_is_not_here_is_404_through_the_doors(home, door):
    assert _error(door.get("/agent-messages/tickets/home-261119-77", params={"reader": "s"})) == (404, "ticket_unknown")
    assert _error(door.get("/agent-messages/tickets/not-an-id", params={"reader": "s"})) == (404, "ticket_unknown")


def test_the_door_takes_the_waiting_mark_and_the_due_day_and_refuses_a_form_that_is_not_one(home, door):
    ticket = outside_ticket()
    body = {"from_session": "ses_x", "from_title": "notes", "text": "waits"}
    assert door.post(f"/agent-messages/tickets/{ticket}/entries", json={**body, "waiting": True, "due": "2026-12-01"}).json()[
        "status"] == "waiting"
    assert ticket_index.get(ticket).due == "2026-12-01"
    assert _error(door.post(f"/agent-messages/tickets/{ticket}/entries", json={**body, "due": 20261201})) == (400, "ticket_bad_relay")
    assert _error(door.post(f"/agent-messages/tickets/{ticket}/entries", json={**body, "due": "soon"})) == (400, "ticket_bad_due")
