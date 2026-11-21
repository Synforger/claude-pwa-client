"""Handing a ticket to another tab: the holder moves, the tab is told in one line, and nothing changes when it is not told."""
from __future__ import annotations

import re

import pytest
from fastapi import HTTPException

from backend.jsonl.jsonl_predicates import AGENT_MESSAGE_OPENING
from backend.tests.async_run import run
from backend.tests.tickets.samples import asked_at_of, ticket_env  # noqa: F401
from backend.tickets import (answer_delivery, answer_queue, ticket_answer, ticket_file, ticket_index, ticket_pass,
                             ticket_service)


@pytest.fixture
def delivered(monkeypatch):
    """What was typed to which tab; every tab is reachable and takes what is typed."""
    typed: list[tuple[str, str]] = []

    async def deliver(tab_id, text):
        typed.append((tab_id, text))
        return {"ok": True}

    monkeypatch.setattr(ticket_pass, "deliver_or_keep", deliver)
    monkeypatch.setattr(ticket_pass, "tab_reachable", lambda tab_id: True)
    return typed


def _ticket() -> str:
    return run(ticket_service.open_ticket("ses_a", "Title", "Request", operator_said=False))["id"]


def _code(coroutine) -> str:
    with pytest.raises(HTTPException) as refused:
        run(coroutine)
    return refused.value.detail["code"]


def test_the_holder_moves_to_the_tab_and_a_passed_line_says_who_gave_it_to_whom(ticket_env, delivered):
    ticket = _ticket()
    assert run(ticket_pass.pass_ticket("ses_a", ticket, "ses_b")) == {"ok": True, "id": ticket, "to": "ses_b"}
    assert ticket_index.get(ticket).holder == "ses_b" and ticket_index.get(ticket).opener == "ses_a"
    last = ticket_file.read(ticket_env.tickets, ticket)[-1]
    assert (last["kind"], last["tab"], last["to"], last["text"]) == ("passed", "ses_a", "ses_b", "")


def test_the_tab_is_told_in_one_line_with_the_ticket_in_the_tag_of_the_usual_envelope(ticket_env, delivered):
    ticket = _ticket()
    run(ticket_pass.pass_ticket("ses_a", ticket, "ses_b"))
    [(tab, message)] = delivered
    opening, tag, body, closing = message.split("\n")
    assert tab == "ses_b" and opening == AGENT_MESSAGE_OPENING
    assert tag == f'<agent-message from="client work" session="ses_a" ticket="{ticket}">'
    assert body == f"票 {ticket} を渡されました。 `tabs ticket show {ticket} --since-mine` で読んでください"
    assert closing == "</agent-message>"


def test_the_tab_may_be_named_by_its_name(ticket_env, delivered):
    ticket = _ticket()
    assert run(ticket_pass.pass_ticket("ses_a", ticket, "slides"))["to"] == "ses_c"


def test_the_request_is_not_in_the_line_so_nobody_rewrites_it_on_the_way(ticket_env, delivered):
    run(ticket_pass.pass_ticket("ses_a", _ticket(), "ses_b"))
    assert "Request" not in delivered[0][1] and "Title" not in delivered[0][1]


def test_a_ticket_that_waits_for_the_operator_is_not_handed_over(ticket_env, delivered):
    ticket = _ticket()
    run(ticket_service.ask("ses_a", ticket, "decide", "A or B?", "A"))
    assert _code(ticket_pass.pass_ticket("ses_a", ticket, "ses_b")) == "ticket_waiting_operator"
    assert delivered == [] and ticket_index.get(ticket).holder == "ses_a"


def test_a_closed_ticket_is_not_handed_over(ticket_env, delivered):
    ticket = _ticket()
    run(ticket_service.close("ses_a", ticket, ""))
    assert _code(ticket_pass.pass_ticket("ses_a", ticket, "ses_b")) == "ticket_closed"
    assert delivered == []


def test_a_ticket_is_not_handed_to_the_tab_that_hands_it(ticket_env, delivered):
    assert _code(ticket_pass.pass_ticket("ses_a", _ticket(), "ses_a")) == "ticket_to_self"


def test_a_tab_that_does_not_exist_is_the_message_doors_unknown_receiver(ticket_env, delivered):
    assert _code(ticket_pass.pass_ticket("ses_a", _ticket(), "nobody")) == "agent_message_unknown_receiver"


@pytest.mark.parametrize("refused_tab", ["ses_a", "ses_b"])
def test_when_the_sender_or_the_tab_has_not_read_the_boundary_nothing_is_told_and_nothing_moves(ticket_env, delivered, refused_tab):
    ticket = _ticket()
    ticket_env.guard.use("covers", covers={"refuse_sessions": [f"conv-{refused_tab}"]})
    assert _code(ticket_pass.pass_ticket("ses_a", ticket, "ses_b")) == "ticket_outside_place"
    assert delivered == [] and ticket_index.get(ticket).holder == "ses_a"
    assert [entry["kind"] for entry in ticket_file.read(ticket_env.tickets, ticket)] == ["opened"]


def test_a_tab_that_cannot_be_reached_leaves_the_ticket_as_it_was(ticket_env, delivered, monkeypatch):
    monkeypatch.setattr(ticket_pass, "tab_reachable", lambda tab_id: False)
    ticket = _ticket()
    assert _code(ticket_pass.pass_ticket("ses_a", ticket, "ses_b")) == "agent_message_receiver_not_running"
    assert ticket_index.get(ticket).holder == "ses_a"


def test_a_delivery_that_fails_leaves_the_ticket_as_it_was(ticket_env, monkeypatch):
    async def fail(tab_id, text):
        raise HTTPException(409, detail={"code": "agent_message_receiver_not_ready", "message": "not ready"})

    monkeypatch.setattr(ticket_pass, "deliver_or_keep", fail)
    monkeypatch.setattr(ticket_pass, "tab_reachable", lambda tab_id: True)
    ticket = _ticket()
    assert _code(ticket_pass.pass_ticket("ses_a", ticket, "ses_b")) == "agent_message_receiver_not_ready"
    assert ticket_index.get(ticket).holder == "ses_a"
    assert len(ticket_file.read(ticket_env.tickets, ticket)) == 1


def test_a_line_kept_for_a_tab_the_account_hold_stopped_still_moves_the_ticket_and_says_so(ticket_env, monkeypatch):
    async def keep(tab_id, text):
        return {"ok": True, "kept": True}

    monkeypatch.setattr(ticket_pass, "deliver_or_keep", keep)
    monkeypatch.setattr(ticket_pass, "tab_reachable", lambda tab_id: True)
    ticket = _ticket()
    assert run(ticket_pass.pass_ticket("ses_a", ticket, "ses_b")) == {"ok": True, "id": ticket, "to": "ses_b", "kept": True}
    assert ticket_index.get(ticket).holder == "ses_b"


def test_a_ticket_that_asks_the_operator_while_the_line_is_on_its_way_is_not_moved(ticket_env, monkeypatch):
    ticket = _ticket()

    async def deliver_then_ask(tab_id, text):
        await ticket_service.ask("ses_a", ticket, "mac", "plug it in", None)
        return {"ok": True}

    monkeypatch.setattr(ticket_pass, "deliver_or_keep", deliver_then_ask)
    monkeypatch.setattr(ticket_pass, "tab_reachable", lambda tab_id: True)
    assert _code(ticket_pass.pass_ticket("ses_a", ticket, "ses_b")) == "ticket_waiting_operator"
    assert ticket_index.get(ticket).holder == "ses_a"


def test_a_child_that_is_handed_a_ticket_by_its_parent_gets_the_work(ticket_env, delivered, monkeypatch):
    handed: list[tuple[str, str]] = []

    async def hand(sender, receiver):
        handed.append((sender, receiver))

    monkeypatch.setattr(ticket_pass, "hand_over_work", hand)
    run(ticket_pass.pass_ticket("ses_a", _ticket(), "ses_b"))
    assert handed == [("ses_a", "ses_b")]


def test_the_envelope_is_rejected_when_the_message_doors_form_changes(ticket_env, monkeypatch):
    monkeypatch.setattr(ticket_pass, "envelope", lambda *args: "other opening\n<x>\nbody")
    with pytest.raises(ValueError):
        ticket_pass.notice_envelope("ses_a", "client work", "home-261119-01")
    assert re.fullmatch(r"票 \S+ を渡されました。.*", ticket_pass.notice_text("home-261119-01"))


def _answered(ticket_env, monkeypatch) -> tuple[str, answer_queue.AnswerKey]:
    """A ticket the operator answered, its answer still in the queue (= its delivery is not started)."""
    monkeypatch.setattr(answer_delivery, "start_delivery", lambda key: None)
    ticket = _ticket()
    run(ticket_service.ask("ses_a", ticket, "decide", "A or B?", "A"))
    asked_at = asked_at_of(ticket_env.tickets, ticket)
    run(ticket_answer.answer(ticket, asked_at, "Take B", False))
    return ticket, answer_queue.AnswerKey(ticket, asked_at)


def test_a_ticket_is_not_handed_over_until_the_operators_answer_has_reached_its_holder(ticket_env, delivered, monkeypatch):
    ticket, key = _answered(ticket_env, monkeypatch)
    assert _code(ticket_pass.pass_ticket("ses_a", ticket, "ses_b")) == "ticket_answer_pending"
    assert delivered == [] and ticket_index.get(ticket).holder == "ses_a"
    answer_queue.remove(key)
    assert run(ticket_pass.pass_ticket("ses_a", ticket, "ses_b"))["to"] == "ses_b"


def test_an_answer_that_is_queued_while_the_tab_is_told_stops_the_ticket_from_moving(ticket_env, monkeypatch):
    ticket = _ticket()

    async def answer_arrives_meanwhile(tab_id, text):
        answer_queue.add(answer_queue.AnswerKey(ticket, "2026-11-19T00:00:00.000+00:00"))
        return {"ok": True}

    monkeypatch.setattr(ticket_pass, "deliver_or_keep", answer_arrives_meanwhile)
    monkeypatch.setattr(ticket_pass, "tab_reachable", lambda tab_id: True)
    assert _code(ticket_pass.pass_ticket("ses_a", ticket, "ses_b")) == "ticket_answer_pending"
    assert ticket_index.get(ticket).holder == "ses_a"
