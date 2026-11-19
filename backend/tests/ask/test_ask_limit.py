"""An ask whose turn a usage limit ends answers `ask_held` at once and cancels the continuation Claude Code booked
(`backend/ask/ask_turn.py`, `limit_watch.py`, `turn_limit.py`). The record is a real file the made-up tab writes to
as Claude Code would."""
from __future__ import annotations

import asyncio
import json
import time

import pytest
from fastapi import HTTPException

from backend.ask import ask_turn, limit_watch, turn_waiters
from backend.tests.ask.conftest import TAB
from backend.tests.async_run import run
from backend.tests.limit_samples import iso, limit_notice_row, limit_stop_row, message_row

LIMIT_TEXT = "You've hit your 5-hour limit · resets 8:30am (Asia/Tokyo)"
BOOKED = "Usage limit reached · continuing automatically at 8:30am · esc to cancel"
CANCELLED = "Automatic continue cancelled · /rate-limit-options to re-arm"


@pytest.fixture
def record(head, tmp_path, monkeypatch):
    """The tab's record, with an earlier turn in it; the waits are made short."""
    path = tmp_path / "head.jsonl"
    _write(path, message_row("old", None, "user", "an earlier question", iso(time.time() - 3600)))
    head.record = path
    head.answers = False
    monkeypatch.setattr(limit_watch, "POLL_SEC", 0.01)
    monkeypatch.setattr(limit_watch, "SHORT_POLL_SEC", 0.01)
    monkeypatch.setattr(limit_watch, "CANCEL_WAIT_SEC", 0.1)
    monkeypatch.setattr(limit_watch, "ANSWER_ROW_WAIT_SEC", 0.3)
    return path


def _write(path, *rows) -> None:
    with path.open("a", encoding="utf-8") as file:
        for row in rows:
            file.write(json.dumps(row) + "\n")


def _limit_rows(*, booked: bool = True, transient: bool = False) -> list[dict]:
    now = iso(time.time())
    stop = limit_stop_row("lim", "q", now)
    stop["message"]["content"] = [{"type": "text", "text": LIMIT_TEXT}]
    if transient:
        stop["apiErrorIsTransient"] = True
    return [message_row("q", None, "user", "the question", now), stop] + (
        [limit_notice_row("note", "lim", now, BOOKED)] if booked else [])


def _held(coroutine) -> dict:
    with pytest.raises(HTTPException) as caught:
        run(coroutine)
    assert (caught.value.status_code, caught.value.detail["code"]) == (409, "ask_held")
    return caught.value.detail["params"]


def test_a_limit_answers_held_with_its_text_and_cancels_the_booked_continuation(head, record):
    head.after_typing = lambda: _write(record, *_limit_rows())
    head.after_escape = lambda: _write(record, limit_notice_row("c", "note", iso(time.time()), CANCELLED))
    params = _held(ask_turn.ask(TAB, "Describe the tavern.", timeout_sec=30))
    assert params == {"id": TAB, "reason": "limit_stop", "limit_message": LIMIT_TEXT, "continuation_cancelled": True}
    assert head.keys == ["Escape"] and turn_waiters._waiters == {}


def test_an_escape_that_cancels_nothing_is_pressed_again_once(head, record):
    head.after_typing = lambda: _write(record, *_limit_rows())
    assert _held(ask_turn.ask(TAB, "hello", timeout_sec=30))["continuation_cancelled"] is False
    assert head.keys == ["Escape", "Escape"]


def test_a_limit_that_booked_nothing_presses_nothing(head, record):
    head.after_typing = lambda: _write(record, *_limit_rows(booked=False))
    assert _held(ask_turn.ask(TAB, "hello", timeout_sec=30))["continuation_cancelled"] is None
    assert head.keys == []


def test_a_passing_429_is_not_a_limit_and_the_answer_that_follows_is_given(head, record):
    def type_it() -> None:
        _write(record, *_limit_rows(booked=False, transient=True))
        loop = asyncio.get_running_loop()
        loop.call_later(0.05, _write, record, message_row("a", "lim", "assistant", "the answer", iso(time.time())))
        loop.call_later(0.06, turn_waiters.turn_ended, TAB, "the answer")
    head.after_typing = type_it
    assert run(ask_turn.ask(TAB, "hello", timeout_sec=30))["answer"] == "the answer"


def test_a_stop_that_comes_before_the_limit_row_is_written_still_answers_held(head, record, monkeypatch):
    def type_it() -> None:
        loop = asyncio.get_running_loop()
        loop.call_soon(turn_waiters.turn_ended, TAB, LIMIT_TEXT)
        loop.call_later(0.05, lambda: _write(record, *_limit_rows(booked=False)))
    head.after_typing = type_it
    monkeypatch.setattr(limit_watch, "POLL_SEC", 10.0)      # the watch does not see it first: the Stop's read must
    assert _held(ask_turn.ask(TAB, "hello", timeout_sec=30))["reason"] == "limit_stop"


def test_a_limit_from_before_the_typing_in_a_reopened_record_is_not_this_turns(head, record, tmp_path):
    reopened = tmp_path / "reopened.jsonl"
    old = iso(time.time() - 3600)
    _write(reopened, message_row("q0", None, "user", "an old question", old), limit_stop_row("old-lim", "q0", old))

    def type_it() -> None:
        head.record = reopened
        asyncio.get_running_loop().call_soon(turn_waiters.turn_ended, TAB, "the answer")
        _write(reopened, message_row("a", "old-lim", "assistant", "the answer", iso(time.time())))
    head.after_typing = type_it
    assert run(ask_turn.ask(TAB, "hello", timeout_sec=30))["answer"] == "the answer"


def test_a_tab_with_no_record_yet_has_the_limit_of_the_record_its_question_started(head, record, tmp_path):
    started = tmp_path / "started.jsonl"
    head.record = None

    def type_it() -> None:
        head.record = started
        _write(started, *_limit_rows(booked=False))
    head.after_typing = type_it
    assert _held(ask_turn.ask(TAB, "hello", timeout_sec=30))["limit_message"] == LIMIT_TEXT


def test_a_tab_held_before_the_typing_says_it_was_the_account_hold(head):
    head.held = True
    with pytest.raises(HTTPException) as caught:
        run(ask_turn.ask(TAB, "hello"))
    assert caught.value.detail["params"] == {"id": TAB, "reason": "account_hold"}
