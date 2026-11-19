"""An ask types its text into a tab set up for it and answers with the turn's last answer (`backend/ask/ask_turn.py`).

The tab, the delivery and the hooks are made up: a typed text is answered by a `Stop` on the next turn of the loop, as
the real hook would come after the turn.
"""
from __future__ import annotations

import pytest
from fastapi import HTTPException

from backend.ask import ask_turn, turn_waiters
from backend.tests.ask.conftest import NAME, TAB
from backend.tests.async_run import run


def _refusal(coroutine) -> tuple[int, str]:
    with pytest.raises(HTTPException) as caught:
        run(coroutine)
    return caught.value.status_code, caught.value.detail["code"]


def test_the_answer_is_the_last_answer_of_the_turn_the_text_started(head):
    assert run(ask_turn.ask(NAME, "Describe the tavern.")) == {"ok": True, "id": TAB, "answer": "the answer"}
    assert head.typed == [("Describe the tavern.", False)]
    assert turn_waiters._waiters == {}                                   # the wait ends with the ask


def test_a_tab_whose_agent_does_not_take_asks_is_not_typed_into(head):
    head.config = {"launch_alias": "worker"}
    assert _refusal(ask_turn.ask(TAB, "hello")) == (403, "ask_not_allowed")
    assert head.typed == []


def test_an_unknown_tab_has_the_askers_code(head):
    assert _refusal(ask_turn.ask("nobody", "hello")) == (404, "ask_unknown_tab")


def test_a_second_ask_while_one_waits_is_refused(head):
    turn_waiters.start_waiting(TAB)
    assert _refusal(ask_turn.ask(TAB, "hello")) == (409, "ask_in_progress")
    assert head.typed == []


def test_a_tab_in_the_middle_of_other_work_is_not_typed_into(head):
    head.busy = True
    assert _refusal(ask_turn.ask(TAB, "hello")) == (409, "ask_tab_busy")
    assert head.typed == [] and turn_waiters._waiters == {}


def test_a_tab_held_by_the_account_line_is_not_woken(head):
    head.held = True
    assert _refusal(ask_turn.ask(TAB, "hello")) == (409, "ask_held")
    assert head.typed == []


def test_fresh_clears_the_conversation_first_and_a_stop_before_the_text_is_not_the_answer(head):
    assert run(ask_turn.ask(TAB, "Describe the tavern.", fresh=True))["answer"] == "the answer"
    assert head.typed == [("/clear", None), ("Describe the tavern.", False)]


def test_fresh_on_a_tab_that_was_woken_types_the_text_as_to_a_running_one(head):
    head.woke = True
    run(ask_turn.ask(TAB, "hello", fresh=True))
    assert head.typed == [("/clear", None), ("hello", False)]


def test_fresh_on_a_tab_with_no_claude_lets_the_text_start_a_new_conversation(head):
    head.running = False
    run(ask_turn.ask(TAB, "hello", fresh=True))
    assert head.typed == [("hello", False)]


def test_a_clear_that_opens_no_conversation_asks_nothing(head, monkeypatch):
    head.opens = False
    monkeypatch.setattr(ask_turn, "CLEAR_WAIT_SEC", 0.05)
    assert _refusal(ask_turn.ask(TAB, "hello", fresh=True)) == (409, "ask_not_ready")
    assert head.typed == [("/clear", None)]


def test_a_turn_that_does_not_end_in_time_is_stopped(head):
    head.answers = False
    assert _refusal(ask_turn.ask(TAB, "hello", timeout_sec=0.05)) == (504, "ask_timeout")
    assert head.keys == ["Escape"] and turn_waiters._waiters == {}


@pytest.mark.parametrize(("code", "expected"), [
    ("agent_message_receiver_not_ready", (409, "ask_not_ready")),
    ("agent_message_not_taken", (409, "ask_not_ready")),
    ("agent_message_unconfirmed", (500, "ask_unconfirmed")),
])
def test_a_failed_delivery_has_the_askers_code(head, code, expected):
    head.delivery_error = (409, code, "no")
    assert _refusal(ask_turn.ask(TAB, "hello")) == expected
    assert turn_waiters._waiters == {}
