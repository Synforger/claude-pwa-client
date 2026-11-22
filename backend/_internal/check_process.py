"""Runs one configured check command as a process that ends with the wait for it.

A command run in a worker thread cannot be cancelled: the wait would end at a stop of the backend and the process would
go on, and the exit of the backend waits for that thread. Here a wait that is cancelled or times out kills the command
and what it started.

Used by `routes/agent_messages.py` and `tickets/guard_command.py`.
"""
from __future__ import annotations

import asyncio
import contextlib
import os
import signal
import subprocess


async def run_check_process(argv: list[str], timeout_sec: float) -> subprocess.CompletedProcess[str]:
    """Run `argv` to its end and return its exit code and what it printed. Raises `subprocess.TimeoutExpired` after
    `timeout_sec`, and `OSError` when it cannot start."""
    # A session of its own, so that what the command started is killed with it.
    process = await asyncio.create_subprocess_exec(
        *argv, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE, start_new_session=True)
    ended = False
    try:
        out, err = await asyncio.wait_for(process.communicate(), timeout_sec)
        ended = True
    except asyncio.TimeoutError:
        raise subprocess.TimeoutExpired(argv, timeout_sec) from None
    finally:
        if not ended:
            # The group can outlive its leader, so it is killed also when the leader has exited already.
            with contextlib.suppress(ProcessLookupError, PermissionError):
                os.killpg(process.pid, signal.SIGKILL)
            await process.wait()
    return subprocess.CompletedProcess(argv, process.returncode, out.decode("utf-8", "replace"),
                                       err.decode("utf-8", "replace"))
