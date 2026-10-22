"""Stops the claude of a tab and makes sure it is gone before anything starts in its place.

Removing a tab's tmux session hangs up the claude inside, which normally ends it. Nothing waited for that,
so a restart or an account move could start the next claude while the previous one was still shutting down,
and a claude that ignored the hang-up would have kept running with no tab to show it. Called by the session
routes (restart, account move, delete).
"""

from __future__ import annotations

import asyncio
import logging

import psutil

from backend.terminal.pty_discover import claude_pid_in_pane
from backend.terminal.runner import kill_tmux_session

logger = logging.getLogger(__name__)

#: How long a hung-up claude gets to end on its own before it is killed
STOP_WAIT_SEC = 5.0
#: How long a killed claude gets to disappear from the process table
KILL_WAIT_SEC = 2.0


def _wait_gone(process: psutil.Process, timeout_sec: float) -> bool:
    """True once `process` has ended (= waits at most `timeout_sec`)."""
    gone, _alive = psutil.wait_procs([process], timeout=timeout_sec)
    return bool(gone)


def stop_claude(session_id: str) -> bool:
    """Remove a tab's tmux session and wait until the claude that ran in it has ended, killing it when it
    outlives `STOP_WAIT_SEC`. True when no claude of the tab is left running. Blocks; callers on the event
    loop use `stop_tab`."""
    pid = claude_pid_in_pane(session_id)
    process = None
    if pid is not None:
        try:
            process = psutil.Process(pid)
        except psutil.NoSuchProcess:
            process = None
    kill_tmux_session(session_id)
    if process is None or _wait_gone(process, STOP_WAIT_SEC):
        return True
    logger.warning("claude of session=%s pid=%s outlived its tmux session; killing it", session_id, pid)
    try:
        process.kill()
    except psutil.NoSuchProcess:
        return True
    if _wait_gone(process, KILL_WAIT_SEC):
        return True
    logger.error("claude of session=%s pid=%s is still running after a kill", session_id, pid)
    return False


async def stop_tab(session_id: str) -> bool:
    """`stop_claude` off the event loop."""
    return await asyncio.to_thread(stop_claude, session_id)
