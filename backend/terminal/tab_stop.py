"""Stops the claude of a tab and makes sure it is gone before anything starts in its place.

The claude is ended first and the tab's tmux session is removed after it is gone. A claude that stays is still seen
in its pane, so nothing starts a second one beside it and the next try finds the same process. Called by the session
routes (restart, account move, delete).
"""

from __future__ import annotations

import asyncio
import logging

import psutil

from backend.terminal.pty_discover import claude_pid_in_pane
from backend.terminal.runner import kill_tmux_session

logger = logging.getLogger(__name__)

#: How long a claude asked to end gets to end on its own before it is killed
STOP_WAIT_SEC = 5.0
#: How long a killed claude gets to disappear from the process table
KILL_WAIT_SEC = 2.0


def _wait_gone(process: psutil.Process, timeout_sec: float) -> bool:
    """True once `process` has ended (= waits at most `timeout_sec`)."""
    gone, _alive = psutil.wait_procs([process], timeout=timeout_sec)
    return bool(gone)


def stop_claude(session_id: str) -> bool:
    """End the claude in a tab's pane (SIGTERM, then a kill when it outlives `STOP_WAIT_SEC`) and then remove the
    tab's tmux session. False when that claude is still running: the tmux session is then left as it was. Blocks;
    callers on the event loop use `stop_tab`."""
    pid = claude_pid_in_pane(session_id)
    if pid is not None and not _end_claude(session_id, pid):
        return False
    kill_tmux_session(session_id)
    return True


def _end_claude(session_id: str, pid: int) -> bool:
    """True once the claude `pid` is gone."""
    try:
        process = psutil.Process(pid)
        process.terminate()
        if _wait_gone(process, STOP_WAIT_SEC):
            return True
        logger.warning("claude of session=%s pid=%s did not end when asked; killing it", session_id, pid)
        process.kill()
        if _wait_gone(process, KILL_WAIT_SEC):
            return True
    except psutil.NoSuchProcess:
        return True
    except psutil.AccessDenied:
        logger.error("claude of session=%s pid=%s may not be signalled", session_id, pid, exc_info=True)
        return False
    logger.error("claude of session=%s pid=%s is still running after a kill", session_id, pid)
    return False


async def stop_tab(session_id: str) -> bool:
    """`stop_claude` off the event loop."""
    return await asyncio.to_thread(stop_claude, session_id)
