"""Tests for the report of an event loop that stood still: the stacks name the call that held it."""
from __future__ import annotations

import asyncio
import logging
import time

from backend.observability.loop_stall import STALL_FILE_NAME, loop_stall_watch, stall_seconds


def _hold_the_loop_with_a_blocking_call(seconds: float) -> None:
    time.sleep(seconds)


def test_a_loop_held_by_a_blocking_call_leaves_the_stacks_and_a_warning(tmp_path, caplog):
    # Intent: a backend that stops answering under load says which call held it, so the cause is named, not guessed.
    async def scenario():
        watch = asyncio.create_task(loop_stall_watch(tmp_path, stall_sec=0.3, beat_sec=0.05))
        await asyncio.sleep(0.2)
        _hold_the_loop_with_a_blocking_call(0.8)
        await asyncio.sleep(0.2)
        watch.cancel()
        try:
            await watch
        except asyncio.CancelledError:
            pass

    with caplog.at_level(logging.WARNING, logger="backend.observability.loop_stall"):
        asyncio.run(scenario())
    report = (tmp_path / STALL_FILE_NAME).read_text(encoding="utf-8")
    assert "Timeout" in report
    assert "_hold_the_loop_with_a_blocking_call" in report
    assert "loop stood still" in report
    assert any("loop stall: the event loop stood still" in r.getMessage() for r in caplog.records)


def test_a_loop_that_keeps_running_writes_nothing(tmp_path):
    async def scenario():
        watch = asyncio.create_task(loop_stall_watch(tmp_path, stall_sec=0.3, beat_sec=0.05))
        await asyncio.sleep(0.5)
        watch.cancel()
        try:
            await watch
        except asyncio.CancelledError:
            pass

    asyncio.run(scenario())
    assert (tmp_path / STALL_FILE_NAME).read_text(encoding="utf-8") == ""


def test_the_time_stood_still_is_what_the_loop_slept_past_its_beat():
    assert stall_seconds(10.0, 11.0, 1.0) == 0.0
    assert stall_seconds(10.0, 31.0, 1.0) == 20.0
    assert stall_seconds(10.0, 10.5, 1.0) == 0.0
