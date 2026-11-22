"""The messages kept while a window is open (`permission_window/window_hold.py`)."""
from __future__ import annotations

import asyncio

from backend.tests.async_run import run
from backend.permission_window import window_hold as hold
from backend.permission_window import window_state as state
from backend.tests.permission_window.conftest import SID, call_row, result_row

LS = {"command": "ls"}


def open_a_window():
    state.fold_row(SID, call_row("toolu_1", "Bash", LS))
    state.open_window(SID, "Bash", LS, now=1.0)


def test_nothing_is_kept_when_nothing_is_open():
    assert hold.hold_if_open(SID, "hello") is None


def test_a_text_is_kept_while_a_window_is_open_and_answered_as_held():
    open_a_window()
    assert hold.hold_if_open(SID, "hello", "send-1") == {"ok": True, "held": "window"}


def test_a_pending_plan_and_a_question_keep_texts_too(tab):
    tab["pending_plan"] = {"tool_use_id": "p", "plan": "", "choices": []}
    assert hold.hold_if_open(SID, "while the plan waits") == {"ok": True, "held": "window"}


def test_kept_texts_are_typed_in_order_when_the_window_closes():
    typed = []

    async def sender(session_id, text):
        typed.append((session_id, text))
        return {"ok": True}

    async def scenario():
        hold.install(sender)
        open_a_window()
        hold.hold_if_open(SID, "first")
        hold.hold_if_open(SID, "second")
        assert typed == []
        state.fold_row(SID, result_row("toolu_1"))
        for _ in range(5):
            await asyncio.sleep(0)
    run(scenario())
    assert typed == [(SID, "first"), (SID, "second")]


def test_a_text_that_comes_while_the_kept_ones_are_typed_goes_behind_them():
    typed = []
    gate = {}

    async def scenario():
        gate["open"] = asyncio.Event()

        async def sender(session_id, text):
            typed.append(text)
            await gate["open"].wait()
            return {"ok": True}

        hold.install(sender)
        open_a_window()
        hold.hold_if_open(SID, "first")
        state.fold_row(SID, result_row("toolu_1"))
        await asyncio.sleep(0)
        assert hold.hold_if_open(SID, "late") == {"ok": True, "held": "window"}
        gate["open"].set()
        for _ in range(5):
            await asyncio.sleep(0)
    run(scenario())
    assert typed == ["first", "late"]


def test_a_window_that_opens_again_stops_the_typing_and_the_rest_wait():
    typed = []

    async def scenario():
        async def sender(session_id, text):
            typed.append(text)
            state.fold_row(SID, call_row("toolu_2", "Bash", {"command": "again"}))
            state.open_window(SID, "Bash", {"command": "again"}, now=2.0)
            return {"ok": True}

        hold.install(sender)
        open_a_window()
        hold.hold_if_open(SID, "first")
        hold.hold_if_open(SID, "second")
        state.fold_row(SID, result_row("toolu_1"))
        for _ in range(5):
            await asyncio.sleep(0)
    run(scenario())
    assert typed == ["first"]
    assert hold._kept[SID] == [("second", None)]


def test_a_second_window_of_the_same_batch_keeps_the_texts_waiting():
    typed = []

    async def scenario():
        async def sender(session_id, text):
            typed.append(text)
            return {"ok": True}

        hold.install(sender)
        state.fold_row(SID, call_row("toolu_1", "Bash", {"command": "a"}))
        state.fold_row(SID, call_row("toolu_2", "Bash", {"command": "b"}))
        state.open_window(SID, "Bash", {"command": "a"}, now=1.0)
        state.open_window(SID, "Bash", {"command": "b"}, now=1.0)
        hold.hold_if_open(SID, "kept")
        state.fold_row(SID, result_row("toolu_1"))
        for _ in range(5):
            await asyncio.sleep(0)
        assert typed == []
        state.fold_row(SID, result_row("toolu_2"))
        for _ in range(5):
            await asyncio.sleep(0)
    run(scenario())
    assert typed == ["kept"]


def test_a_text_that_is_not_taken_tells_the_screen_that_sent_it(monkeypatch):
    told = []
    monkeypatch.setattr(hold.jsonl_event_broadcaster, "publish", lambda sid, event: told.append((sid, event)))

    async def scenario():
        async def sender(session_id, text):
            return {"ok": False, "reason": "not_ready"}

        hold.install(sender)
        open_a_window()
        hold.hold_if_open(SID, "lost", "send-9")
        state.fold_row(SID, result_row("toolu_1"))
        for _ in range(5):
            await asyncio.sleep(0)
    run(scenario())
    assert told == [(SID, {"type": "send_failed", "sid": SID, "send_id": "send-9"})]
