"""A stop of the backend ends an ask wherever it waits (`backend/ask/ask_turn.py`, `turn_waiters.py`): nothing more is
typed, and the code says whether the question may have reached the tab."""
from __future__ import annotations

import asyncio
import json
import time

import pytest
from fastapi import HTTPException

from backend.ask import ask_turn, limit_watch, screen_watch, turn_waiters
from backend.tests.ask.conftest import TAB
from backend.tests.async_run import run
from backend.tests.limit_samples import iso, limit_notice_row, limit_stop_row, message_row

NOT_ASKED = (409, "ask_not_ready", "backend_stopping")
MAY_BE_ASKED = (500, "ask_unconfirmed", "backend_stopping")
BOOKED = "Usage limit reached · continuing automatically at 8:30am · esc to cancel"
CANCELLED = "Automatic continue cancelled · /rate-limit-options to re-arm"


@pytest.fixture(autouse=True)
def running(monkeypatch):
    """The backend runs when a test begins, and again for the tests after it."""
    monkeypatch.setattr(turn_waiters, "_stopping", False)


def _ended(coroutine) -> tuple[int, str, str]:
    with pytest.raises(HTTPException) as caught:
        run(asyncio.wait_for(coroutine, 5))
    detail = caught.value.detail
    assert turn_waiters._waiters == {}
    return caught.value.status_code, detail["code"], detail["params"]["reason"]


def _stop_soon() -> None:
    asyncio.get_running_loop().call_later(0.02, turn_waiters.end_waits)


async def _hang(*_args) -> None:
    _stop_soon()
    await asyncio.Event().wait()


def test_an_ask_that_comes_while_stopping_asks_nothing(head):
    turn_waiters.end_waits()
    assert _ended(ask_turn.ask(TAB, "hello")) == NOT_ASKED
    assert head.typed == []


def test_a_stop_while_the_tab_wakes_asks_nothing(head, monkeypatch):
    monkeypatch.setattr(ask_turn, "wake_tab", _hang)
    assert _ended(ask_turn.ask(TAB, "hello")) == NOT_ASKED
    assert head.typed == []


@pytest.mark.parametrize(("asked", "typed"), [
    ({"fresh": True}, "/clear"),
    ({"resume": "earlier-uuid"}, "/resume earlier-uuid"),
])
def test_a_stop_while_a_conversation_opens_asks_nothing_and_presses_nothing(head, monkeypatch, asked, typed):
    head.opens = False
    send = ask_turn.pty_send

    async def send_then_stop(*args, **_):
        _stop_soon()
        return await send(*args)
    monkeypatch.setattr(ask_turn, "pty_send", send_then_stop)
    assert _ended(ask_turn.ask(TAB, "hello", **asked)) == NOT_ASKED
    assert head.typed == [(typed, None)] and head.keys == []


def test_a_stop_right_before_the_typing_asks_nothing(head, monkeypatch):
    async def prepare(*_args, **_options):
        turn_waiters.end_waits()
        return ask_turn._Ready(False, False, limit_watch.RecordMark(None, 0, time.time()), None)
    monkeypatch.setattr(ask_turn, "_prepare", prepare)
    assert _ended(ask_turn.ask(TAB, "hello")) == NOT_ASKED
    assert head.typed == []


def test_a_stop_during_the_delivery_may_have_asked(head, monkeypatch):
    monkeypatch.setattr(ask_turn, "deliver_message", _hang)
    assert _ended(ask_turn.ask(TAB, "hello")) == MAY_BE_ASKED


def test_a_stop_while_the_answer_is_awaited_leaves_the_turn_alone(head):
    head.answers = False
    head.after_typing = _stop_soon
    assert _ended(ask_turn.ask(TAB, "hello", timeout_sec=30)) == MAY_BE_ASKED
    assert head.keys == []


def test_an_answer_that_is_there_at_the_stop_is_given(head):
    def answer_and_stop() -> None:
        turn_waiters.turn_ended(TAB, "just in time")
        turn_waiters.end_waits()
    head.answers = False
    head.after_typing = lambda: asyncio.get_running_loop().call_later(0.02, answer_and_stop)
    assert run(ask_turn.ask(TAB, "hello", timeout_sec=30))["answer"] == "just in time"


@pytest.mark.parametrize("cancels", [True, False])
def test_a_limit_not_yet_seen_at_the_stop_is_held_after_one_escape(head, tmp_path, monkeypatch, cancels):
    record = tmp_path / "head.jsonl"
    record.write_text(json.dumps(message_row("old", None, "user", "earlier", iso(time.time() - 3600))) + "\n")

    def write(*rows) -> None:
        with record.open("a", encoding="utf-8") as file:
            file.writelines(json.dumps(row) + "\n" for row in rows)

    def limit_then_stop() -> None:
        now = iso(time.time())
        write(message_row("q", None, "user", "the question", now), limit_stop_row("lim", "q", now),
              limit_notice_row("note", "lim", now, BOOKED))
        turn_waiters.end_waits()
    head.record = record
    head.answers = False
    head.after_typing = lambda: asyncio.get_running_loop().call_later(0.05, limit_then_stop)
    if cancels:
        head.after_escape = lambda: write(limit_notice_row("c", "note", iso(time.time()), CANCELLED))
    monkeypatch.setattr(limit_watch, "POLL_SEC", 10.0)
    monkeypatch.setattr(limit_watch, "SHORT_POLL_SEC", 0.01)
    with pytest.raises(HTTPException) as caught:
        run(asyncio.wait_for(ask_turn.ask(TAB, "hello", timeout_sec=30), 2))
    assert caught.value.detail["code"] == "ask_held"
    assert caught.value.detail["params"]["continuation_cancelled"] is cancels
    assert head.keys == ["Escape"]


def test_a_stream_ends_with_the_stop_as_its_last_line(head, monkeypatch):
    head.answers = False
    monkeypatch.setattr(screen_watch, "read_screen", lambda session_id: None)
    monkeypatch.setattr(screen_watch, "read_pasted_counts", lambda session_id: None)

    async def scenario() -> list[dict]:
        events = await ask_turn.ask_stream(TAB, "hello", timeout_sec=30)
        _stop_soon()
        return [event async for event in events]
    seen = run(asyncio.wait_for(scenario(), 5))
    assert (seen[-1]["type"], seen[-1]["code"]) == ("error", "ask_unconfirmed")
    assert seen[-1]["params"]["reason"] == "backend_stopping"


def test_a_stream_that_has_not_typed_fails_as_the_ask_does(head, monkeypatch):
    monkeypatch.setattr(ask_turn, "wake_tab", _hang)
    monkeypatch.setattr(screen_watch, "read_pasted_counts", lambda session_id: None)
    assert _ended(ask_turn.ask_stream(TAB, "hello")) == NOT_ASKED


def test_a_backend_started_again_takes_asks_again(head):
    turn_waiters.end_waits()
    turn_waiters.accept_waits()
    assert run(ask_turn.ask(TAB, "hello"))["answer"] == "the answer"
