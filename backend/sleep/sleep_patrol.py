"""The sleep patrol: looks over the tabs on the rollover's interval, puts the quiet ones of an agent with a `sleep`
setting to sleep, and takes the sleep mark off a tab whose claude runs again.

What a sleep is, and the conditions, are in `docs/reference/sleep.md`. The judgement is `sleep_judgement.py`; the
sleeping itself is `sleeper.py`. A tab wakes by the ordinary start of a tab without a terminal (a message, or the
operator opening it), not by this patrol, which only clears the mark afterwards.
"""
from __future__ import annotations

import asyncio
import logging

import backend.jsonl.jsonl_watcher as jsonl_watcher
from backend._common.state import SessionDef, save_sessions_meta, sessions_meta, sessions_overview
from backend.rollover.rollover import TICK_SEC
from backend.sleep.sleep_judgement import judge
from backend.sleep.sleep_sensors import gather
from backend.sleep.sleep_settings import sleep_minutes
from backend.sleep.sleeper import put_to_sleep
from backend.terminal import input_ready
from backend.terminal.pty_discover import claude_pid_in_pane

logger = logging.getLogger(__name__)

# The reasons a tab was last left awake for, so that the same reasons are logged once however long they last.
_last_reasons: dict[str, tuple[str, ...]] = {}


def _log_reasons(session_id: str, reasons: tuple[str, ...]) -> None:
    if _last_reasons.get(session_id) == reasons:
        return
    _last_reasons[session_id] = reasons
    if reasons:
        logger.info("sleep: awake session=%s reasons=%s", session_id, ",".join(reasons))


async def _clear_when_awake(meta: SessionDef) -> None:
    """Take the sleep mark off a tab whose claude is running again, and say which conversation it opened."""
    session_id = meta.id
    if not input_ready.is_ready(session_id) or await asyncio.to_thread(claude_pid_in_pane, session_id) is None:
        return
    mark, meta.sleep = meta.sleep, None
    save_sessions_meta()
    sessions_overview.notify()
    record = jsonl_watcher.get_jsonl_for(session_id)
    bound = record.stem if record is not None else None
    log = logger.info if bound == mark.claude_sid else logger.warning
    log("sleep: woke session=%s claude_sid=%s bound=%s", session_id, mark.claude_sid, bound)


async def tick() -> list[str]:
    """Look over every tab once. → the tabs put to sleep."""
    slept: list[str] = []
    for session_id in list(sessions_meta):
        meta = sessions_meta.get(session_id)
        if meta is None:
            continue
        if meta.sleep is not None:
            await _clear_when_awake(meta)
            continue
        minutes = sleep_minutes(session_id)
        if minutes is None:
            _last_reasons.pop(session_id, None)
            continue
        reasons = judge(await asyncio.to_thread(gather, session_id, minutes), minutes)
        _log_reasons(session_id, reasons)
        if not reasons and await put_to_sleep(session_id, minutes):
            slept.append(session_id)
    return slept


async def sleep_loop(interval_sec: float = TICK_SEC) -> None:
    """Look over the tabs every `interval_sec` (= the rollover's interval)."""
    logger.info("sleep_loop started (interval=%ds)", interval_sec)
    try:
        while True:
            await asyncio.sleep(interval_sec)
            try:
                await tick()
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("sleep_loop iteration failed")
    except asyncio.CancelledError:
        logger.info("sleep_loop cancelled")
        raise
