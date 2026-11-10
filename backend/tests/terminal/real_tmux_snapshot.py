"""Runs a screen-drawing program in a real tmux pane and returns the snapshot a new terminal would get.

Shared by two tests: `test_screen_capture_real_tmux` (Python, checks the report) and the
frontend test `snapshotRender.test.js`, which runs this module as a command, feeds the
snapshot to a real xterm and compares every cell with an xterm fed the program's own output.

The tmux server is the test's own (a private `-L` socket named after the process), killed when the
scenario ends, so it can never touch the operator's sessions. Claude is not involved: the pane runs
a few lines of Python that print known bytes and wait for input.

    python -m backend.tests.terminal.real_tmux_snapshot <scenario>   (prints one JSON object)
"""
from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path

from starlette.websockets import WebSocketState

from backend.terminal import connect_snapshot, runner
from backend.terminal.runner import PtySession
from backend.terminal.screen_capture import capture_pane_screen

SESSION_ID = "snapshot-scenario"
# How long a scenario may take to put its bytes on the pane: the machine this runs on is often loaded.
PANE_READY_TIMEOUT_SEC = 30.0
STABLE_POLL_SEC = 0.1

# The program prints these bytes, then waits for input so the pane stays as drawn.
_PROGRAM = (
    "import sys\n"
    "sys.stdout.buffer.write(bytes.fromhex(sys.argv[1]))\n"
    "sys.stdout.buffer.flush()\n"
    "sys.stdin.readline()\n"
)

_WIDE_ROW = "┃ " + "x" * 76 + " ┃"


@dataclass(frozen=True)
class Scenario:
    """A program's output and the size of the pane it runs in."""

    cols: int
    rows: int
    output: str


SCENARIOS: dict[str, Scenario] = {
    # colours, attributes, wide characters, a row that fills the width, a coloured blank run,
    # and the cursor left in the middle of the screen
    "colors": Scenario(40, 10, (
        "\x1b[31mred\x1b[0m \x1b[1;32mboldgreen\x1b[0m \x1b[48;5;21mbg256\x1b[0m\r\n"
        "日本語wide \x1b[38;2;10;200;30mtruecolor\x1b[0m\r\n"
        + "X" * 40 + "\r\n"
        "\x1b[4munder\x1b[0m \x1b[7mrev\x1b[0m \x1b[44m   \x1b[0m\r\n"
        "\x1b[3mital\x1b[0m \x1b[9mstrike\x1b[0m \x1b[2mdim\x1b[0m\r\n"
        "\x1b[41m\x1b[K red to the end\x1b[0m\r\n"
        "\x1b[8;4Hcur"
    )),
    # a full-screen program: alternate screen, the cursor hidden
    "alternate": Scenario(30, 6, (
        "main-screen-text\r\n"
        "\x1b[?1049h\x1b[H\x1b[2J\x1b[34malt-line\x1b[0m\x1b[3;2Hx\x1b[?25l"
    )),
    # a framed layout at a desktop terminal size, with the last row filled to its last cell
    "framed": Scenario(80, 24, (
        "\x1b[2J\x1b[H"
        + "\x1b[1;1H╭" + "─" * 78 + "╮"
        + "".join(f"\x1b[{row};1H{_WIDE_ROW}" for row in range(2, 6))
        + "\x1b[6;1H╰" + "─" * 78 + "╯"
        + "\x1b[8;1H\x1b[36m> \x1b[0mtype here"
        + "\x1b[24;1H\x1b[7m" + "status ".ljust(80) + "\x1b[0m"
        + "\x1b[8;12H"
    )),
}


class _CollectingWs:
    """Stands in for the websocket: records what `send_connect_snapshot` sends."""

    client_state = WebSocketState.CONNECTED

    def __init__(self) -> None:
        self.frames: list[bytes] = []

    async def send_bytes(self, data: bytes) -> None:
        self.frames.append(data)

    async def send_text(self, text: str) -> None:
        raise AssertionError(f"no snapshot was captured: {text}")


def _tmux(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run([*runner.tmux_base_argv(), *args], capture_output=True, timeout=30)


def _stop_server() -> None:
    """Kills the test's tmux server and removes its socket file (kill-server leaves the file behind)."""
    asked = _tmux("display-message", "-p", "#{socket_path}")
    _tmux("kill-server")
    socket_path = asked.stdout.decode().strip()
    if asked.returncode == 0 and socket_path:
        Path(socket_path).unlink(missing_ok=True)


def _wait_until_drawn() -> None:
    """Waits until two captures a moment apart agree and the pane holds something."""
    deadline = time.monotonic() + PANE_READY_TIMEOUT_SEC
    previous = None
    while time.monotonic() < deadline:
        screen = capture_pane_screen(SESSION_ID)
        if screen is not None and any(screen.lines) and screen == previous:
            return
        previous = screen
        time.sleep(STABLE_POLL_SEC)
    raise TimeoutError("the scenario program did not draw its screen in time")


def run_scenario(name: str, socket_name: str | None = None) -> dict:
    """Draws scenario `name` in a real tmux pane and returns its program bytes and snapshot (hex)."""
    scenario = SCENARIOS[name]
    socket_name = socket_name or f"cpc-snapshot-{os.getpid()}"
    saved_socket = runner.TMUX_SOCKET_NAME
    saved_env = os.environ.pop("TMUX", None)  # a test run inside tmux must not reach for its server
    runner.TMUX_SOCKET_NAME = socket_name
    try:
        with tempfile.TemporaryDirectory() as folder:
            program = Path(folder) / "program.py"
            program.write_text(_PROGRAM, encoding="utf-8")
            output = scenario.output.encode("utf-8")
            started = _tmux(
                "new-session", "-d", "-s", runner._tmux_session_name(SESSION_ID),
                "-x", str(scenario.cols), "-y", str(scenario.rows),
                f"{sys.executable} {program} {output.hex()}",
            )
            if started.returncode != 0:
                raise RuntimeError(f"tmux new-session failed: {started.stderr.decode()}")
            _wait_until_drawn()
            snapshot = asyncio.run(_snapshot((scenario.rows, scenario.cols)))
        return {
            "name": name, "cols": scenario.cols, "rows": scenario.rows,
            "program_hex": output.hex(), "snapshot_hex": snapshot.hex(),
        }
    finally:
        _stop_server()
        runner.TMUX_SOCKET_NAME = saved_socket
        if saved_env is not None:
            os.environ["TMUX"] = saved_env


async def _snapshot(size: tuple[int, int]) -> bytes:
    """What a terminal of `size` is sent first, through the same code the websocket route runs."""
    session = PtySession(
        session_id=SESSION_ID, process=None, master_fd=-1,  # type: ignore[arg-type]
        output_queue=asyncio.Queue(maxsize=16), exit_event=asyncio.Event(),
    )
    resized: asyncio.Future = asyncio.get_running_loop().create_future()
    resized.set_result(size)
    ws = _CollectingWs()
    await connect_snapshot.send_connect_snapshot(ws, session, resized, asyncio.create_task(asyncio.sleep(30)))
    (frame,) = ws.frames
    return frame


if __name__ == "__main__":
    print(json.dumps(run_scenario(sys.argv[1])))
