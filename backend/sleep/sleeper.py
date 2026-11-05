"""Puts a tab's claude to sleep: ends it the ordinary way and closes the terminal, keeping the conversation it must
reopen on the tab. The reads and writes of the sleep (record, tab definition, process, tmux).

The terminal is closed with the claude, because the tab is then a tab without a terminal, which any message or touch
starts again with `claude --resume` (`terminal/session_resolver.py`). A shell left in the pane would start a new
conversation instead of reopening this one.

Used by `sleep_patrol.py`.
"""
from __future__ import annotations

import asyncio
import logging
import time
from pathlib import Path

import psutil

import backend.jsonl.jsonl_watcher as jsonl_watcher
from backend._common.state import SleepMark, save_sessions_meta, sessions_meta, sessions_overview
from backend.sleep.sleep_judgement import judge
from backend.sleep.sleep_sensors import gather
from backend.terminal.pty_discover import claude_pid_in_pane
from backend.terminal.runner import kill_tmux_session, pty_sessions, terminate_pty_session

logger = logging.getLogger(__name__)

# How long a claude that was asked to end gets to end. Past it the tab stays awake: a claude is never killed here.
EXIT_WAIT_SEC = 20.0


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


async def put_to_sleep(session_id: str, minutes: int) -> bool:
    """Put the tab's claude to sleep if every condition still holds. True when it slept; False leaves the tab awake
    and as it was."""
    meta = sessions_meta.get(session_id)
    if meta is None:
        return False
    facts = await asyncio.to_thread(gather, session_id, minutes)
    if reasons := judge(facts, minutes):
        logger.info("sleep: not now session=%s reasons=%s", session_id, ",".join(reasons))
        return False
    record = jsonl_watcher.get_jsonl_for(session_id)
    if record is None or not await asyncio.to_thread(ends_with_newline, record):
        logger.warning("sleep: the record is missing or ends in a partial line session=%s", session_id)
        return False
    meta.sleep = SleepMark(claude_sid=record.stem, record=str(record), slept_at=int(time.time()),
                          account_id=meta.account_id)
    save_sessions_meta()
    pid = await asyncio.to_thread(claude_pid_in_pane, session_id)
    if pid is None or not await asyncio.to_thread(end_claude, pid):
        meta.sleep = None
        save_sessions_meta()
        logger.warning("sleep: the claude did not end in %.0fs; left awake session=%s", EXIT_WAIT_SEC, session_id)
        return False
    await _close_terminal(session_id)
    sessions_overview.notify()
    logger.info("sleep: session=%s claude_sid=%s idle_min=%d context_pct=%s", session_id, record.stem,
                facts.quiet_minutes or 0, facts.context_pct)
    return True
