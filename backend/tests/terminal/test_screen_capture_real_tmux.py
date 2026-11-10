"""The connect-time snapshot taken from a real tmux pane, on a private tmux socket.

The pane runs a few lines of Python that print known bytes (no Claude). The frontend test
`snapshotRender.test.js` checks that an xterm painted by the same snapshot matches the program's own
output cell for cell; here the report tmux gives back is checked.
"""
from __future__ import annotations

import os
import shutil
import subprocess

import pytest

from backend.terminal import runner
from backend.tests.terminal.real_tmux_snapshot import run_scenario

pytestmark = pytest.mark.skipif(shutil.which("tmux") is None, reason="tmux is not installed")

ESC = "\x1b"


def _snapshot(name: str) -> str:
    socket_name = f"cpc-snapshot-test-{os.getpid()}"
    result = run_scenario(name, socket_name=socket_name)
    return bytes.fromhex(result["snapshot_hex"]).decode("utf-8")


def test_the_cursor_lands_where_the_program_left_it():
    # the program moved to row 8, column 4 and printed "cur": tmux's cursor is at column 7 (1-based)
    text = _snapshot("colors")
    assert text.endswith(f"{ESC}[8;7H{ESC}[?25h")


def test_colours_and_attributes_are_carried():
    text = _snapshot("colors")
    for sequence in ("[31m", "[1m", "[48;5;21m", "[38;2;10;200;30m", "[4m", "[7m", "[3m", "[9m", "[2m"):
        assert f"{ESC}{sequence}" in text, sequence


def test_a_background_that_runs_to_the_edge_is_kept():
    # row 6 was filled red to its end by erase-in-line: the 40 cells include the blank ones
    text = _snapshot("colors")
    row = text.split(f"{ESC}[6;1H")[1].split(f"{ESC}[0m{ESC}[K")[0]
    assert row.startswith(f"{ESC}[41m red to the end")
    assert len(row) - len(f"{ESC}[41m") == 40


def test_the_alternate_screen_is_entered_and_a_hidden_cursor_stays_hidden():
    text = _snapshot("alternate")
    assert text.index(f"{ESC}[?1049h") < text.index(f"{ESC}[2J") < text.index("alt-line")
    assert "main-screen-text" not in text  # the screen being painted is the alternate one
    assert f"{ESC}[?25h" not in text
    assert text.endswith(f"{ESC}[3;3H")


def test_a_screen_at_desktop_size_is_painted_row_by_row():
    text = _snapshot("framed")
    assert "type here" in text
    assert text.count(f"{ESC}[K") == 24
    assert text.endswith(f"{ESC}[8;12H{ESC}[?25h")


def test_the_scenario_leaves_no_tmux_server_behind():
    socket_name = f"cpc-snapshot-test-{os.getpid()}"
    _snapshot("alternate")
    ls = subprocess.run(
        [runner.TMUX_BIN, "-L", socket_name, "list-sessions"], capture_output=True, timeout=30,
    )
    assert ls.returncode != 0
