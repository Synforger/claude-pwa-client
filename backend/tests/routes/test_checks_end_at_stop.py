"""A stop of the backend ends the check commands it waits for, the process as well as the wait, and the ticket channel of
the stream ends quietly. A check left running in a thread holds the exit of the backend until it is over.
"""
from __future__ import annotations

import asyncio
import os
import signal
import sys
from collections.abc import Awaitable, Callable, Iterator
from pathlib import Path

import pytest

from backend._internal import stop_signal
from backend._internal.stop_signal import BackendStopping
from backend.routes import agent_messages, unified_stream
from backend.tickets import guard_command

WAIT_SEC = 3
POLL_SEC = 0.05
# A check that takes longer than the test, with a process of its own below it: both must be gone after a stop.
SLOW_CHECK = (
    "import os, subprocess, sys, time\n"
    "below = subprocess.Popen(['sleep', '30'])\n"
    "open(sys.argv[1], 'w').write('%d %d' % (os.getpid(), below.pid))\n"
    "time.sleep(30)\n"
)


@pytest.fixture(autouse=True)
def backend_running() -> Iterator[None]:
    stop_signal.accept_work()
    yield
    stop_signal.accept_work()


def _is_running(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    return True


async def _until(condition: Callable[[], bool]) -> bool:
    deadline = asyncio.get_running_loop().time() + WAIT_SEC
    while not condition():
        if asyncio.get_running_loop().time() > deadline:
            return False
        await asyncio.sleep(POLL_SEC)
    return True


async def _message_check(command: list[str]) -> None:
    assert (await agent_messages._run_check(command, "text", {}))[0] is None


async def _ticket_check(command: list[str]) -> None:
    with pytest.raises(BackendStopping):
        await guard_command.run_command(command, {})


@pytest.mark.parametrize("run_check", [_message_check, _ticket_check])
def test_a_stop_ends_the_check_and_what_it_started(run_check: Callable[[list[str]], Awaitable[None]],
                                                   tmp_path: Path) -> None:
    pid_path = tmp_path / "pids"

    async def scenario() -> list[int]:
        waiting = asyncio.create_task(run_check([sys.executable, "-c", SLOW_CHECK, str(pid_path)]))
        assert await _until(lambda: pid_path.exists() and len(pid_path.read_text().split()) == 2)
        pids = [int(word) for word in pid_path.read_text().split()]
        try:
            stop_signal.end_work()
            await asyncio.wait_for(waiting, WAIT_SEC)
            await _until(lambda: not any(_is_running(pid) for pid in pids))
            return [pid for pid in pids if _is_running(pid)]
        finally:
            # A red run leaves both running, and the loop would wait for the check's thread at its end.
            for pid in pids:
                if _is_running(pid):
                    os.kill(pid, signal.SIGKILL)

    assert asyncio.run(scenario()) == []


def test_a_stop_ends_the_ticket_channel_without_an_error(monkeypatch: pytest.MonkeyPatch) -> None:
    async def stopped() -> dict:
        raise BackendStopping

    monkeypatch.setattr(unified_stream.ticket_feed, "snapshot", stopped)

    async def scenario() -> None:
        changed = asyncio.Event()
        changed.set()
        await asyncio.wait_for(unified_stream._tickets_pump(object(), changed, ""), WAIT_SEC)

    asyncio.run(scenario())
