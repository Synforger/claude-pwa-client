"""The connect snapshot behind a real control-mode client: the size the terminal asks for is the size captured.

`spawn_pty_session` starts `tmux -CC` on a private socket (the same path a tab takes); the pane runs a few
lines of Python that draw a screen. The terminal's resize goes out as `resize_pty` sends it, and the snapshot
must come back at that size.
"""
from __future__ import annotations

import asyncio
import os
import shutil
import sys
from pathlib import Path

import pytest
from starlette.websockets import WebSocketState

import backend.terminal.connect_snapshot as cs
from backend.terminal import runner

pytestmark = pytest.mark.skipif(shutil.which("tmux") is None, reason="tmux is not installed")

SESSION_ID = "snapshot-control-mode"
PROGRAM = (
    "import sys\n"
    "sys.stdout.write('\\x1b[2J\\x1b[H\\x1b[32mhello\\x1b[0m\\r\\nline2\\x1b[5;3Hcur')\n"
    "sys.stdout.flush()\n"
    "sys.stdin.readline()\n"
)
PANE_DRAW_WAIT_SEC = 1.5


class _Ws:
    client_state = WebSocketState.CONNECTED

    def __init__(self) -> None:
        self.sent: list[bytes | str] = []

    async def send_bytes(self, data: bytes) -> None:
        self.sent.append(data)

    async def send_text(self, text: str) -> None:
        self.sent.append(text)


@pytest.fixture
def private_tmux(monkeypatch, tmp_path):
    """Points the runner at a socket of its own and a pane program that only draws a screen."""
    socket_name = f"cpc-snapshot-cm-{os.getpid()}"
    program = tmp_path / "program.py"
    program.write_text(PROGRAM, encoding="utf-8")
    monkeypatch.delenv("TMUX", raising=False)
    monkeypatch.setattr(runner, "TMUX_SOCKET_NAME", socket_name)
    monkeypatch.setattr(runner, "CLAUDE_PATH", "claude")
    monkeypatch.setattr(runner, "PTY_INITIAL_ARGV", [sys.executable, str(program)])
    monkeypatch.setattr(runner, "tmux_session_env_args", lambda session_id, extra_env: [])
    yield socket_name
    asked = runner._run_tmux("display-message", "-p", "#{socket_path}")
    runner._run_tmux("kill-server")
    if asked is not None and asked.returncode == 0:
        Path(asked.stdout.decode().strip()).unlink(missing_ok=True)


def _snapshot_after_resize(rows: int, cols: int) -> bytes:
    async def scenario() -> bytes:
        session = await runner.spawn_pty_session(SESSION_ID, cwd=os.getcwd())
        try:
            await asyncio.sleep(PANE_DRAW_WAIT_SEC)
            runner.resize_pty(session, rows, cols)  # what the input pump does with the terminal's first size
            resized: asyncio.Future = asyncio.get_running_loop().create_future()
            resized.set_result((rows, cols))
            ws = _Ws()
            await cs.send_connect_snapshot(ws, session, resized, asyncio.create_task(asyncio.sleep(30)))
            (frame,) = ws.sent
            assert isinstance(frame, bytes)
            return frame
        finally:
            await runner.terminate_pty_session(session)

    return asyncio.run(scenario())


@pytest.mark.parametrize("rows,cols", [(24, 80), (50, 160), (30, 100)])
def test_the_snapshot_is_taken_at_the_size_the_terminal_asked_for(private_tmux, rows, cols):
    text = _snapshot_after_resize(rows, cols).decode("utf-8")
    assert text.count("\x1b[K") == rows
    assert "\x1b[32mhello" in text
    assert text.endswith("\x1b[5;6H\x1b[?25h")  # row 5, after "cur" which starts at column 3
