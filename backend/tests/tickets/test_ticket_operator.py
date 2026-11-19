"""What the operator's screen does with a ticket besides answering: read it whole, hand a ticket no tab holds to a tab, and
say it looked at an answer that did not arrive. Also who may ask the operator, and the notifications."""
from __future__ import annotations

import asyncio

import pytest
from fastapi import HTTPException

from backend.tests.async_run import run
from backend.tests.tickets.samples import answered_ticket, asked_at_of, delivery_env, ticket_env, waiting_ticket  # noqa: F401
from backend.tickets import ticket_file, ticket_index, ticket_notify, ticket_operator, ticket_pass, ticket_service


def _code(coroutine) -> str:
    with pytest.raises(HTTPException) as refused:
        run(coroutine)
    return refused.value.detail["code"]


@pytest.fixture
def told(monkeypatch):
    """What was typed to which tab when the operator hands a ticket; every tab is reachable."""
    typed: list[tuple[str, str]] = []

    async def deliver(tab_id, text):
        typed.append((tab_id, text))
        return {"ok": True}

    monkeypatch.setattr(ticket_pass, "deliver_or_keep", deliver)
    monkeypatch.setattr(ticket_pass, "tab_reachable", lambda tab_id: True)
    return typed


@pytest.fixture
def pushed(monkeypatch):
    """What the notifications sent: `(body, title, ticket, tag)`."""
    sent: list[tuple] = []

    async def broadcast(message, title=None, session_id=None, *, ticket=None, tag=None):
        sent.append((message, title, ticket, tag))

    monkeypatch.setattr(ticket_notify, "broadcast_push", broadcast)
    return sent


def test_the_operator_reads_every_line_and_what_the_screen_draws_from(delivery_env):
    ticket = waiting_ticket()
    asked_at = asked_at_of(delivery_env.tickets, ticket)
    read = run(ticket_operator.read(ticket))
    assert [line["kind"] for line in read["entries"]] == ["opened", "asked"]
    assert (read["status"], read["wants"], read["holder"], read["place_outside"]) == ("waiting-operator", "decide", "ses_a", True)
    assert read["answer_pending"] == [] and read["attention"] == "waiting" and read["last_delivery"] is None
    assert read["entries"][1]["at"] == asked_at


def test_a_ticket_with_an_answer_on_its_way_says_so(delivery_env):
    key = answered_ticket(delivery_env)
    read = run(ticket_operator.read(key.ticket))
    assert read["answer_pending"] == [key.asked_at] and read["attention"] is None


def test_an_unknown_ticket_is_not_found(ticket_env):
    assert _code(ticket_operator.read("home-261119-99")) == "ticket_unknown"


def test_the_operator_hands_a_ticket_no_tab_holds_and_the_tab_is_told_first(ticket_env, told):
    ticket = run(ticket_service.open_ticket("ses_a", "T", "R", operator_said=False))["id"]
    ticket_index.put(ticket, ticket_index.get(ticket)._replace(holder=""))
    assert run(ticket_operator.hand_to(ticket, "ses_b")) == {"ok": True, "id": ticket, "to": "ses_b"}
    assert ticket_index.get(ticket).holder == "ses_b"
    [(tab, message)] = told
    assert tab == "ses_b" and f'<agent-message from="operator" session="" ticket="{ticket}">' in message
    assert "操作者から渡されました" in message
    last = ticket_file.read(ticket_env.tickets, ticket)[-1]
    assert (last["kind"], last["tab"], last["to"]) == ("passed", "", "ses_b")


def test_a_ticket_that_waits_for_the_operator_and_has_no_holder_can_be_handed_and_keeps_waiting(ticket_env, told):
    ticket = waiting_ticket()
    ticket_index.put(ticket, ticket_index.get(ticket)._replace(holder=""))
    run(ticket_operator.hand_to(ticket, "ses_c"))
    row = ticket_index.get(ticket)
    assert (row.holder, row.status) == ("ses_c", "waiting-operator")


def test_an_answer_on_its_way_goes_to_the_new_holder(delivery_env, told):
    key = answered_ticket(delivery_env)
    ticket_index.put(key.ticket, ticket_index.get(key.ticket)._replace(holder=""))
    run(ticket_operator.hand_to(key.ticket, "ses_b"))
    assert ticket_index.get(key.ticket).holder == "ses_b"


def test_a_ticket_a_tab_holds_is_not_handed_again_by_the_operator(ticket_env, told):
    ticket = run(ticket_service.open_ticket("ses_a", "T", "R", operator_said=False))["id"]
    assert _code(ticket_operator.hand_to(ticket, "ses_b")) == "ticket_has_holder"
    assert told == []


def test_a_tab_that_cannot_be_told_leaves_the_ticket_as_it_was(ticket_env, told):
    ticket = run(ticket_service.open_ticket("ses_a", "T", "R", operator_said=False))["id"]
    ticket_index.put(ticket, ticket_index.get(ticket)._replace(holder=""))
    assert _code(ticket_operator.hand_to(ticket, "ses_missing")) == "agent_message_unknown_receiver"
    assert ticket_index.get(ticket).holder == ""


def _refused_delivery(env, *, closed: bool = False) -> str:
    key = answered_ticket(env)
    if closed:
        run(ticket_service.close("ses_a", key.ticket, ""))
    ticket_file.append(env.tickets, key.ticket, {"kind": "delivered", "at": ticket_service.now(), "tab": "", "tab_title": "",
                                                 "tier": "", "text": "", "asked_at": key.asked_at, "result": "refused", "to": "ses_a"})
    return key.ticket


def test_looking_at_an_answer_that_did_not_arrive_takes_the_ticket_out_of_the_ones_that_want_a_look(delivery_env):
    ticket = _refused_delivery(delivery_env)
    assert run(ticket_operator.read(ticket))["attention"] == "delivery"
    assert run(ticket_operator.seen(ticket)) == {"ok": True, "id": ticket, "written": True}
    read = run(ticket_operator.read(ticket))
    assert read["attention"] is None and read["entries"][-1]["kind"] == "seen"
    assert run(ticket_operator.seen(ticket)) == {"ok": True, "id": ticket, "written": False}


def test_a_closed_ticket_takes_the_look_too(delivery_env):
    ticket = _refused_delivery(delivery_env, closed=True)
    assert run(ticket_operator.read(ticket))["status"] == "closed"
    assert run(ticket_operator.read(ticket))["attention"] == "delivery"
    assert run(ticket_operator.seen(ticket))["written"] is True


def test_there_is_nothing_to_look_at_for_a_ticket_whose_answers_arrived(delivery_env):
    ticket = waiting_ticket()
    assert run(ticket_operator.seen(ticket))["written"] is False
    assert [line["kind"] for line in ticket_file.read(delivery_env.tickets, ticket)] == ["opened", "asked"]


def test_only_the_tab_that_holds_the_ticket_may_ask_the_operator(ticket_env):
    ticket = run(ticket_service.open_ticket("ses_a", "T", "R", operator_said=False))["id"]
    ticket_index.put(ticket, ticket_index.get(ticket)._replace(holder="ses_b"))
    assert _code(ticket_service.ask("ses_a", ticket, "decide", "A or B?", None)) == "ticket_not_holder"
    assert ticket_index.get(ticket).status == "open"
    assert run(ticket_service.ask("ses_b", ticket, "decide", "A or B?", None))["status"] == "waiting-operator"


def test_asking_tells_the_operators_devices_with_the_ticket_title(ticket_env, pushed):
    async def scenario() -> str:
        ticket = (await ticket_service.open_ticket("ses_a", "Fix the title", "R", operator_said=False))["id"]
        await ticket_service.ask("ses_a", ticket, "decide", "A or B?", None)
        await asyncio.sleep(0.05)
        return ticket

    ticket = run(scenario())
    assert pushed == [("Waiting for your decision", "📌 Fix the title", ticket, f"ticket-{ticket}")]


def test_a_ticket_kept_inside_a_boundary_is_notified_by_its_id_only(ticket_env, pushed, monkeypatch):
    ticket = run(ticket_service.open_ticket("ses_a", "Secret title", "R", operator_said=False))["id"]
    inside = ticket_index.get(ticket)._replace(place_key="inside")
    ticket_index.put(ticket, inside)
    run(ticket_notify.notify(ticket, "no_holder"))
    assert pushed == [("No tab holds this ticket", f"📌 Ticket {ticket}", ticket, f"ticket-{ticket}")]


def test_a_failing_push_does_not_fail_the_notification(ticket_env, monkeypatch):
    async def broken(*args, **kwargs):
        raise RuntimeError("push is down")

    monkeypatch.setattr(ticket_notify, "broadcast_push", broken)
    ticket = run(ticket_service.open_ticket("ses_a", "T", "R", operator_said=False))["id"]
    run(ticket_notify.notify(ticket, "waiting"))
