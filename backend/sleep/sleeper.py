"""Puts a tab's claude to sleep: ends it the ordinary way and closes the terminal, keeping the conversation it must
reopen on the tab. The reads and writes of the sleep (record, tab definition, process, tmux).

The terminal is closed with the claude, because the tab is then a tab without a terminal, which any message or touch
starts again with `claude --resume` (`terminal/session_resolver.py`). A shell left in the pane would start a new
conversation instead of reopening this one.

A tab is "falling asleep" from the moment it is decided until its terminal is closed (`is_falling_asleep`). A message
typed in that time would reach a claude that is ending and be lost, so the delivery of messages waits for it
(`wait_until_asleep`) and then delivers to the sleeping tab. The patrol's sleeps take the tab's claim
(`accounts/tab_claim.py`), so that they never end a tab the account fallback or hold is working on.

Used by `sleep_patrol.py` (= `put_to_sleep`), by a parent tab putting its child to sleep (= `sleep_now`, through
`routes/child_sessions.py`), by the account hold, which stops a tab at a break it has read itself (= `sleep_at_break`),
and by the delivery of messages (= `wait_until_asleep`, `routes/agent_messages.py`).
"""
from __future__ import annotations

import asyncio
import logging
import time
from pathlib import Path

import psutil

import backend.jsonl.jsonl_watcher as jsonl_watcher
from backend._common.state import SessionDef, SleepMark, save_sessions_meta, sessions_meta, sessions_overview
from backend.accounts.tab_claim import claimed
from backend.sleep.sleep_judgement import PASSING, judge
from backend.sleep.sleep_sensors import gather
from backend.terminal.pty_discover import claude_pid_in_pane
from backend.terminal.runner import kill_tmux_session, pty_sessions, terminate_pty_session

logger = logging.getLogger(__name__)

# How long a claude that was asked to end gets to end. Past it the tab stays awake: a claude is never killed here.
EXIT_WAIT_SEC = 20.0
# How long a sleep asked for by hand waits for the conditions that pass by themselves (= `PASSING`), and how often it
# looks again. A child that has just reported is still writing the end of its answer.
PASSING_WAIT_SEC = 60.0
PASSING_LOOK_SEC = 2.0
# How long a delivery waits for a tab that is falling asleep: the claude's end, and the closing of the terminal.
FALLING_ASLEEP_WAIT_SEC = EXIT_WAIT_SEC + 5.0
FALLING_ASLEEP_LOOK_SEC = 0.2
# Why a tab whose conditions all held was still left awake, and the answer for a tab that is not in the list.
UNKNOWN_TAB = "unknown_tab"
CLAIMED = "claimed"

# The tabs falling asleep now. The backend runs on one event loop, so a set needs no lock.
_falling_asleep: set[str] = set()


def is_falling_asleep(session_id: str) -> bool:
    """Whether the tab is being put to sleep now (= its claude may be ending)."""
    return session_id in _falling_asleep


async def wait_until_asleep(session_id: str) -> None:
    """Wait while the tab is falling asleep, up to `FALLING_ASLEEP_WAIT_SEC`. A message delivered after this reaches
    the tab as it is then: asleep, or awake when the sleep was given up."""
    loop = asyncio.get_running_loop()
    deadline = loop.time() + FALLING_ASLEEP_WAIT_SEC
    while session_id in _falling_asleep and loop.time() < deadline:
        await asyncio.sleep(FALLING_ASLEEP_LOOK_SEC)
PARTIAL_RECORD = "partial_record"
CLAUDE_DID_NOT_END = "claude_did_not_end"


def ends_with_newline(record: Path) -> bool:
    """Whether the record exists and its last line is complete (= the conversation can be reopened from it)."""
    try:
        size = record.stat().st_size
        if size == 0:
            return False
        with record.open("rb") as fh:
            fh.seek(size - 1)
            return fh.read(1) == b"\n"
    except OSError:
        return False


def end_claude(pid: int) -> bool:
    """Ask the claude `pid` to end (= SIGTERM, which it answers by saving and exiting) and wait for it. True once it
    is gone. It is not killed when it stays: the caller leaves the tab awake. Blocks."""
    try:
        process = psutil.Process(pid)
        process.terminate()
    except psutil.NoSuchProcess:
        return True
    gone, _alive = psutil.wait_procs([process], timeout=EXIT_WAIT_SEC)
    return bool(gone)


async def _close_terminal(session_id: str) -> None:
    """Remove the tab's tmux session and forget the terminal the backend held for it."""
    session = pty_sessions.pop(session_id, None)
    await asyncio.to_thread(kill_tmux_session, session_id)
    if session is not None:
        await terminate_pty_session(session)


async def put_to_sleep(session_id: str, minutes: int, *, reported: bool = False, stopped_by_limit: bool = False,
                       pressure: bool = False) -> bool:
    """Put the tab's claude to sleep if every condition still holds, for the patrol: after `minutes` of quiet, as a
    child that reported its work done (`reported`, `stopped_by_limit` when a usage limit stopped its turn), or as the
    one tab put to sleep while the machine is short of memory (`pressure`, only for the log). It takes the tab's claim
    and leaves a tab another feature holds. True when it slept; False leaves the tab awake and as it was."""
    with claimed(session_id) as mine:
        if not mine:
            logger.info("sleep: not now session=%s reasons=%s", session_id, CLAIMED)
            return False
        return not await _sleep(session_id, minutes, by_hand=False, stopped_by_limit=stopped_by_limit,
                                reported=reported, pressure=pressure)


async def sleep_now(session_id: str) -> tuple[str, ...]:
    """Put the tab's claude to sleep now, for its parent: without waiting for the quiet minutes, and waiting up to
    `PASSING_WAIT_SEC` for the conditions that pass by themselves. → the conditions that kept it awake; empty when it
    slept."""
    loop = asyncio.get_running_loop()
    deadline = loop.time() + PASSING_WAIT_SEC
    while True:
        reasons = await _sleep(session_id, 0, by_hand=True)
        if not reasons or not PASSING.issuperset(reasons) or loop.time() >= deadline:
            return reasons
        await asyncio.sleep(PASSING_LOOK_SEC)


async def sleep_at_break(session_id: str, *, stopped_by_limit: bool = False) -> tuple[str, ...]:
    """Put the tab's claude to sleep now, once, for a caller that has read that the tab is at a break (`stopped_by_limit`
    when a usage limit stopped its turn, which is judged as `judge` does). It does not wait for conditions that pass by
    themselves. → the conditions that kept it awake; empty when it slept."""
    return await _sleep(session_id, 0, by_hand=True, stopped_by_limit=stopped_by_limit)


async def _sleep(session_id: str, minutes: int, by_hand: bool, stopped_by_limit: bool = False, reported: bool = False,
                 pressure: bool = False) -> tuple[str, ...]:
    """Put the tab's claude to sleep if every condition still holds. → the conditions that kept it awake (= the tab
    is as it was); empty when it slept."""
    meta = sessions_meta.get(session_id)
    if meta is None:
        return (UNKNOWN_TAB,)
    if session_id in _falling_asleep:
        return (CLAIMED,)
    _falling_asleep.add(session_id)
    try:
        return await _end(meta, minutes, by_hand, stopped_by_limit, reported, pressure)
    finally:
        _falling_asleep.discard(session_id)


async def _end(meta: SessionDef, minutes: int, by_hand: bool, stopped_by_limit: bool, reported: bool,
               pressure: bool) -> tuple[str, ...]:
    """The body of `_sleep`, while the tab is marked as falling asleep."""
    session_id = meta.id
    facts = await asyncio.to_thread(gather, session_id, minutes, by_hand, stopped_by_limit, reported)
    if reasons := judge(facts, minutes, by_hand, stopped_by_limit, reported):
        logger.info("sleep: not now session=%s reasons=%s", session_id, ",".join(reasons))
        return reasons
    record = jsonl_watcher.get_jsonl_for(session_id)
    if record is None or not await asyncio.to_thread(ends_with_newline, record):
        logger.warning("sleep: the record is missing or ends in a partial line session=%s", session_id)
        return (PARTIAL_RECORD,)
    meta.sleep = SleepMark(claude_sid=record.stem, record=str(record), slept_at=int(time.time()),
                          account_id=meta.account_id)
    save_sessions_meta()
    pid = await asyncio.to_thread(claude_pid_in_pane, session_id)
    if pid is None or not await asyncio.to_thread(end_claude, pid):
        meta.sleep = None
        save_sessions_meta()
        logger.warning("sleep: the claude did not end in %.0fs; left awake session=%s", EXIT_WAIT_SEC, session_id)
        return (CLAUDE_DID_NOT_END,)
    await _close_terminal(session_id)
    sessions_overview.notify()
    flags = "".join(f" {name}=1" for name, on in (("by_hand", by_hand), ("reported", reported), ("pressure", pressure))
                    if on)
    logger.info("sleep: session=%s claude_sid=%s idle_min=%d context_pct=%s%s", session_id, record.stem,
                facts.quiet_minutes or 0, facts.context_pct, flags)
    return ()
