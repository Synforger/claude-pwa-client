"""The sleep patrol: looks over the tabs on the rollover's interval, puts the quiet ones of an agent with a `sleep`
setting to sleep, and takes the sleep mark off a tab whose claude runs again. It also puts to sleep the children that
reported their work done, and, while the machine is short of memory, the one tab quiet the longest of those that may
sleep after the agent's `pressure_minutes`. Each look writes the machine's memory facts to the log when they change.

What a sleep is, and the conditions, are in `docs/reference/sleep.md`. The judgement is `sleep_judgement.py`; the
sleeping itself is `sleeper.py`. A tab wakes by the ordinary start of a tab without a terminal (a message, or the
operator opening it), not by this patrol, which only clears the mark afterwards.
"""
from __future__ import annotations

import asyncio
import logging

import backend.jsonl.jsonl_watcher as jsonl_watcher
from backend._common.state import SessionDef, save_sessions_meta, sessions_meta, sessions_overview
from backend.child_watch.child_memo import DONE, memo_state
from backend.child_watch.child_work import memo_of
from backend.rollover.rollover import TICK_SEC
from backend.sleep.memory_sensor import MemoryFacts, read_memory
from backend.sleep.record_facts import RecordFacts
from backend.sleep.sleep_judgement import REPORTED_QUIET_MINUTES, is_short_of_memory, judge, pick_under_pressure
from backend.sleep.sleep_sensors import gather, note_woken, record_facts_of
from backend.sleep.sleep_settings import pressure_minutes, sleep_minutes
from backend.sleep.sleeper import put_to_sleep
from backend.terminal import input_ready
from backend.terminal.pty_discover import claude_pid_in_pane

logger = logging.getLogger(__name__)

# The reasons a tab was last left awake for, so that the same reasons are logged once however long they last.
_last_reasons: dict[str, tuple[str, ...]] = {}
# The memory facts of the previous look (= the pressure level must be high on two looks in a row, and the log line is
# written when the level changes or swap was read back).
_last_memory = MemoryFacts()
# Swap read back since the previous look, in MB, from which a look is written to the log although the level is the same.
SWAPINS_LOG_MB = 1.0


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
    note_woken(session_id)
    save_sessions_meta()
    sessions_overview.notify()
    record = jsonl_watcher.get_jsonl_for(session_id)
    bound = record.stem if record is not None else None
    log = logger.info if bound == mark.claude_sid else logger.warning
    log("sleep: woke session=%s claude_sid=%s bound=%s", session_id, mark.claude_sid, bound)


async def tick() -> list[str]:
    """Look over every tab once. → the tabs put to sleep."""
    slept: list[str] = []
    candidates: list[tuple[str, float]] = []
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
        if await asyncio.to_thread(_has_reported, meta):
            if await _sleep_reported(session_id):
                slept.append(session_id)
            continue
        pressure = pressure_minutes(session_id)
        facts = await asyncio.to_thread(gather, session_id, min(minutes, pressure or minutes))
        reasons = judge(facts, minutes)
        _log_reasons(session_id, reasons)
        if not reasons:
            if await put_to_sleep(session_id, minutes):
                slept.append(session_id)
        elif pressure is not None and not judge(facts, pressure):
            candidates.append((session_id, facts.quiet_minutes or 0.0))
    if await _short_of_memory() and (chosen := pick_under_pressure(candidates)) is not None:
        if await put_to_sleep(chosen, pressure_minutes(chosen) or 0, pressure=True):
            slept.append(chosen)
    return slept


def _has_reported(meta: SessionDef) -> bool:
    """Whether the tab is a child whose memo says it reported its work done. Blocking (the memo)."""
    return meta.child and memo_state(memo_of(meta)) == DONE


async def _sleep_reported(session_id: str) -> bool:
    """Put a child that reported its work done to sleep once it answered since it started and was quiet for a while
    (= `sleep_judgement`). A turn a usage limit stopped counts as its break. True when it slept."""
    stopped = (await asyncio.to_thread(_record_of, session_id)).limit_stop is not None
    facts = await asyncio.to_thread(gather, session_id, REPORTED_QUIET_MINUTES, False, stopped, True)
    reasons = judge(facts, REPORTED_QUIET_MINUTES, stopped_by_limit=stopped, reported=True)
    _log_reasons(session_id, reasons)
    return not reasons and await put_to_sleep(session_id, REPORTED_QUIET_MINUTES, reported=True,
                                              stopped_by_limit=stopped)


def _record_of(session_id: str) -> RecordFacts:
    """The facts of the tab's conversation record; empty when it has none or it cannot be read. Blocking."""
    record = jsonl_watcher.get_jsonl_for(session_id)
    try:
        return record_facts_of(record) if record is not None else RecordFacts()
    except OSError:
        return RecordFacts()


async def _short_of_memory() -> bool:
    """Read the machine's memory once per look, write it to the log when it changed, and say whether the machine is
    short of memory (= `is_short_of_memory`)."""
    global _last_memory
    memory = await asyncio.to_thread(read_memory)
    previous, _last_memory = _last_memory, memory
    if memory.level != previous.level or (memory.swapins_mb or 0.0) >= SWAPINS_LOG_MB:
        logger.info("sleep: memory level=%s swapins_mb=%s swap_used_mb=%s", memory.level,
                    None if memory.swapins_mb is None else round(memory.swapins_mb),
                    None if memory.swap_used_mb is None else round(memory.swap_used_mb))
    return is_short_of_memory(previous.level, memory.level)


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
