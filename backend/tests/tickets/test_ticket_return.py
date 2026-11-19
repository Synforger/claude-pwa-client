"""Giving a ticket back when the tab that holds it is closed: to the tab that asked first (told in one line), or to nobody
when that tab is gone too; and what is never touched."""
from __future__ import annotations

import pytest

from backend._common.state import SessionDef
from backend.tests.async_run import run
from backend.tests.tickets.samples import delivery_env, refusal, waiting_ticket  # noqa: F401
from backend.tests.tickets.samples import ticket_env  # noqa: F401
from backend.tickets import ticket_file, ticket_index, ticket_return, ticket_service


def _open_held_by(env, holder: str = "ses_b") -> str:
    ticket = run(ticket_service.open_ticket("ses_a", "Title", "Request", operator_said=False))["id"]
    ticket_index.put(ticket, ticket_index.get(ticket)._replace(holder=holder))
    return ticket


def _returned_lines(env, ticket: str) -> list[dict]:
    return [entry for entry in ticket_file.read(env.tickets, ticket) if entry["kind"] == "returned"]


def test_a_holder_that_is_here_leaves_the_ticket_alone(delivery_env):
    ticket = _open_held_by(delivery_env)
    assert run(ticket_return.tick()) == [] and ticket_index.get(ticket).holder == "ses_b"
    assert delivery_env.typed == [] and _returned_lines(delivery_env, ticket) == []


def test_a_closed_holder_gives_the_ticket_back_to_the_tab_that_asked_first_and_that_tab_is_told(delivery_env):
    ticket = _open_held_by(delivery_env)
    del delivery_env.tabs["ses_b"]
    assert run(ticket_return.tick()) == [ticket]
    assert ticket_index.get(ticket).holder == "ses_a"
    [line] = _returned_lines(delivery_env, ticket)
    assert (line["from"], line["to"], line["tab"], line["text"]) == ("ses_b", "ses_a", "", "")
    [(tab, message)] = delivery_env.typed
    assert tab == "ses_a" and message.startswith("Sent by the client (the operator did not type this):\n")
    assert f'<ticket-returned ticket="{ticket}">' in message
    assert f"票 {ticket} を持っていたタブが閉じられたので、 あなたに戻りました" in message


def test_a_ticket_that_is_back_is_not_given_back_again(delivery_env):
    _open_held_by(delivery_env)
    del delivery_env.tabs["ses_b"]
    run(ticket_return.tick())
    assert run(ticket_return.tick()) == [] and len(delivery_env.typed) == 1


def test_when_the_tab_that_asked_first_is_gone_too_the_holder_is_empty_and_nobody_is_told(delivery_env):
    ticket = _open_held_by(delivery_env)
    del delivery_env.tabs["ses_b"], delivery_env.tabs["ses_a"]
    assert run(ticket_return.tick()) == [ticket]
    assert ticket_index.get(ticket).holder == ""
    assert [(line["from"], line["to"]) for line in _returned_lines(delivery_env, ticket)] == [("ses_b", "")]
    assert delivery_env.typed == []


def test_a_ticket_that_waits_for_the_operator_goes_back_and_keeps_waiting(delivery_env):
    ticket = waiting_ticket(holder="ses_b")
    del delivery_env.tabs["ses_b"]
    run(ticket_return.tick())
    row = ticket_index.get(ticket)
    assert (row.holder, row.status, row.wants) == ("ses_a", "waiting-operator", "decide")


def test_a_closed_ticket_is_not_looked_at(delivery_env):
    ticket = _open_held_by(delivery_env)
    run(ticket_service.close("ses_a", ticket, ""))
    del delivery_env.tabs["ses_b"]
    assert run(ticket_return.tick()) == [] and ticket_index.get(ticket).holder == "ses_b"


def test_a_holder_on_a_machine_that_is_not_configured_is_taken_to_be_there(delivery_env):
    ticket = _open_held_by(delivery_env, holder="office:ses_x")
    assert run(ticket_return.tick()) == [] and ticket_index.get(ticket).holder == "office:ses_x"


@pytest.mark.parametrize("listed", [True, None])
def test_a_holder_on_the_other_machine_stays_unless_that_machine_answers_and_does_not_list_it(delivery_env, monkeypatch, listed):
    ticket = _open_held_by(delivery_env, holder="company:ses_x")
    monkeypatch.setattr(ticket_return.ticket_relay, "holder_listed", _listing(listed))
    assert run(ticket_return.tick()) == [] and ticket_index.get(ticket).holder == "company:ses_x"
    assert delivery_env.typed == []


def test_a_holder_on_the_other_machine_that_its_machine_no_longer_lists_goes_back_to_the_tab_that_asked_first(delivery_env, monkeypatch):
    ticket = _open_held_by(delivery_env, holder="company:ses_x")
    monkeypatch.setattr(ticket_return.ticket_relay, "holder_listed", _listing(False))
    assert run(ticket_return.tick()) == [ticket] and ticket_index.get(ticket).holder == "ses_a"
    [line] = _returned_lines(delivery_env, ticket)
    assert (line["from"], line["to"]) == ("company:ses_x", "ses_a")
    assert [tab for tab, _ in delivery_env.typed] == ["ses_a"]


def test_a_holder_on_the_other_machine_is_looked_up_only_when_the_ticket_is_held_there(delivery_env, monkeypatch):
    asked = []
    monkeypatch.setattr(ticket_return.ticket_relay, "holder_listed", _listing(False, asked))
    _open_held_by(delivery_env, holder="ses_b")
    run(ticket_return.tick())
    assert asked == []


def _listing(answer, asked=None):
    async def holder_listed(holder):
        if asked is not None:
            asked.append(holder)
        return answer

    return holder_listed


def test_the_ticket_does_not_move_when_the_tab_cannot_be_told(delivery_env):
    ticket = _open_held_by(delivery_env)
    del delivery_env.tabs["ses_b"]
    delivery_env.fail["ses_a"] = refusal(409, "agent_message_receiver_not_ready")
    assert run(ticket_return.tick()) == [] and ticket_index.get(ticket).holder == "ses_b"
    delivery_env.fail.clear()
    assert run(ticket_return.tick()) == [ticket] and ticket_index.get(ticket).holder == "ses_a"


def test_a_ticket_handed_over_while_the_tab_was_being_told_is_not_taken_back(delivery_env):
    ticket = _open_held_by(delivery_env)
    del delivery_env.tabs["ses_b"]

    class HandsOver(dict):
        def __contains__(self, tab_id):                          # called when the tab is told: the ticket moves meanwhile
            ticket_index.put(ticket, ticket_index.get(ticket)._replace(holder="ses_c"))
            return False

    delivery_env.fail = HandsOver()
    assert run(ticket_return.tick()) == [] and ticket_index.get(ticket).holder == "ses_c"


def test_a_child_that_asked_first_has_its_memo_set_back_to_working(delivery_env):
    ticket = _open_held_by(delivery_env)
    delivery_env.tabs["ses_a"] = SessionDef(id="ses_a", agent_id="agent_a", title="child", created_at=0, tier="projects/AP",
                                            child=True, parent_id="ses_c")
    del delivery_env.tabs["ses_b"]
    run(ticket_return.tick())
    assert ticket_index.get(ticket).holder == "ses_a" and delivery_env.handed == [("ses_c", "ses_a")]
