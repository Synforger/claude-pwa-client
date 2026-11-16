"""Which commands of a claude end with its conversation (`backend/rollover/tool_shells.py`), and both readers of the
process table (the watch with psutil, `tabs` with `ps`) giving the same answer on real processes."""
from __future__ import annotations

import importlib.util
import subprocess
import sys
import time
from pathlib import Path

import pytest

import backend.rollover.rollover as watch
from backend.rollover.tool_shells import (
    COMMAND_HEAD_CHARS, TOOL_SHELL_MARK, ProcessRow, command_of, elapsed_text, own_tool_shell, seconds_of_elapsed,
    tool_shells)

TABS = Path(__file__).resolve().parents[2] / "cli" / "tabs.py"
SNAPSHOT = f"/home/agent/.claude{TOOL_SHELL_MARK}zsh-1-abc.sh"


def _shell_line(command: str) -> str:
    """A command line as Claude Code's tool shell writes it (each `'` of the command as `'"'"'`)."""
    quoted = command.replace("'", "'\"'\"'")
    return (f"/bin/zsh -c source {SNAPSHOT} 2>/dev/null || true && \\builtin setopt NO_EQUALS 2>/dev/null || true "
            f"&& eval '{quoted}' < /dev/null && pwd -P >| /tmp/claude-1-cwd")


CLAUDE = 100
ROWS = [
    ProcessRow(pid=CLAUDE, parent_pid=1, command_line="claude"),
    ProcessRow(pid=201, parent_pid=CLAUDE, command_line=_shell_line("bash r94-full.sh > out.txt 2>&1"), elapsed_seconds=7200),
    ProcessRow(pid=202, parent_pid=201, command_line="bash r94-full.sh"),                  # under a shell: not counted twice
    ProcessRow(pid=203, parent_pid=CLAUDE, command_line="caffeinate -i -t 300", elapsed_seconds=10),
    ProcessRow(pid=204, parent_pid=CLAUDE, command_line="node /opt/mcp/server.js --stdio", elapsed_seconds=9000),
    ProcessRow(pid=205, parent_pid=CLAUDE, command_line=_shell_line("tabs rollover continue"), elapsed_seconds=1),
    ProcessRow(pid=206, parent_pid=205, command_line="python3 tabs.py rollover continue"),
    ProcessRow(pid=207, parent_pid=999, command_line=_shell_line("sleep 9"), elapsed_seconds=50),  # another claude's
]


def test_only_the_tool_shells_directly_under_claude_count():
    assert [shell.pid for shell in tool_shells(ROWS, CLAUDE)] == [201, 205]


def test_the_shell_of_the_call_that_asks_is_left_out():
    (shell,) = tool_shells(ROWS, CLAUDE, leaving_out=205)
    assert (shell.pid, shell.elapsed_seconds, shell.command) == (201, 7200, "bash r94-full.sh > out.txt 2>&1")


def test_the_shell_a_process_runs_under_is_its_nearest_tool_shell_ancestor():
    assert own_tool_shell(ROWS, 206).pid == 205
    assert own_tool_shell(ROWS, 205).pid == 205
    assert own_tool_shell(ROWS, 203) is None                  # claude's own child, not in a tool call
    assert own_tool_shell(ROWS, 12345) is None                # not in the table


def test_a_loop_in_the_table_ends_the_walk():
    rows = [ProcessRow(pid=1, parent_pid=2, command_line="a"), ProcessRow(pid=2, parent_pid=1, command_line="b")]
    assert own_tool_shell(rows, 1) is None


@pytest.mark.parametrize("command", [
    "sleep 120",
    "cd /tmp && grep -E 'a|b' x.txt | sed -e 's#x#y#'",
    "echo \"it's\" '' done",
])
def test_the_command_is_read_back_from_the_shell_s_command_line(command):
    assert command_of(_shell_line(command)) == command


def test_a_long_command_is_cut_and_one_without_eval_shows_its_start():
    assert command_of(_shell_line("x" * 300)) == "x" * (COMMAND_HEAD_CHARS - 1) + "…"
    assert command_of(f"/bin/zsh -c source {SNAPSHOT}\n  && run") == f"/bin/zsh -c source {SNAPSHOT} && run"


@pytest.mark.parametrize("text, seconds", [
    ("00:07", 7.0), ("12:34", 754.0), ("1:02:03", 3723.0), ("2-01:00:00", 176400.0), (" 05:00 ", 300.0),
    ("", None), ("abc", None), ("1:2:3:4", None), ("x-01:00", None),
])
def test_the_elapsed_time_ps_writes_is_read_as_seconds(text, seconds):
    assert seconds_of_elapsed(text) == seconds


@pytest.mark.parametrize("seconds, text", [(None, "?"), (40.5, "40秒"), (300, "5分"), (7500, "2時間5分")])
def test_the_elapsed_time_is_written_for_a_person(seconds, text):
    assert elapsed_text(seconds) == text


# --- real processes ---------------------------------------------------------------------------


FAKE_CLAUDE = """
import subprocess, sys, time
shell = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)", sys.argv[1], "eval 'sleep 60' < /dev/null"])
other = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)", "--stdio"])
print(shell.pid, other.pid, flush=True)
time.sleep(60)
"""


@pytest.fixture
def fake_claude():
    """A process standing for claude, with a child shaped like a tool's shell and another child that is not."""
    claude = subprocess.Popen([sys.executable, "-c", FAKE_CLAUDE, SNAPSHOT], stdout=subprocess.PIPE, text=True)
    try:
        shell, other = (int(pid) for pid in claude.stdout.readline().split())
        time.sleep(0.2)
        yield claude.pid, shell, other
    finally:
        subprocess.run(["pkill", "-P", str(claude.pid)], check=False)
        claude.kill()
        claude.wait()


def test_the_watch_reads_the_tool_shells_of_a_real_claude(fake_claude, monkeypatch):
    claude, shell, _other = fake_claude
    monkeypatch.setattr(watch, "claude_pid_in_pane", lambda sid: claude)
    (found,) = watch.background_shells("ses_a")
    assert (found.pid, found.command) == (shell, "sleep 60")
    assert found.elapsed_seconds is not None and found.elapsed_seconds >= 0
    monkeypatch.setattr(watch, "claude_pid_in_pane", lambda sid: None)
    assert watch.background_shells("ses_a") == []


def test_tabs_reads_the_same_shells_with_ps(fake_claude):
    claude, shell, _other = fake_claude
    # Loaded the way the tests of `tabs` load it: it is a command, not a module of the package
    spec = importlib.util.spec_from_file_location("tabs_process_table", TABS)
    tabs = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(tabs)
    (found,) = tool_shells(tabs.process_table(), claude)
    assert (found.pid, found.command) == (shell, "sleep 60")
