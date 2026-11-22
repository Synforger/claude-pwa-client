"""How the text of a chat message reaches a tmux pane.

The text is typed with `send-keys -l`. tmux reads its own command line, so a sentence that starts with `-` or
ends with `;` must still arrive as the characters it is, and a control character in the text must not reach the
pane as a key. The pure tests check the arguments `_build_send_keys_chain` hands to tmux; the real-tmux tests send
through `tmux_send_keys` into a private tmux server (own `-L` socket, no config file) whose only pane runs a
short Python program that records the bytes it receives and then ends by itself, which also ends the server.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

import pytest

from backend.terminal import runner

# The pane program: puts the terminal in raw mode (so CR stays CR), says it is ready, records every byte it
# receives until the input has been quiet for a moment, and ends. A hard limit ends it even if nothing arrives.
_PANE_PROGRAM = """
import os, select, sys, time, tty
out = sys.argv[1]
tty.setraw(0)
open(out + ".ready", "w").close()
start = last = time.monotonic()
data = b""
while time.monotonic() - start < 20:
    if select.select([0], [], [], 0.1)[0]:
        data += os.read(0, 65536)
        last = time.monotonic()
    elif data and time.monotonic() - last > 0.4:
        break
open(out + ".tmp", "w").write(data.hex())
os.rename(out + ".tmp", out)
"""

READY_TIMEOUT_SEC = 5.0
RESULT_TIMEOUT_SEC = 6.0

needs_tmux = pytest.mark.skipif(shutil.which("tmux") is None, reason="tmux is not installed")


# --- the text as it is typed ---------------------------------------------------------------------------------


def test_text_is_typed_after_the_end_of_options_marker():
    args, _ = runner._build_send_keys_chain("pwa-x", text="hello")
    assert args == [["send-keys", "-t", "pwa-x", "-l", "--", "hello"]]


def test_a_sentence_starting_with_a_dash_is_not_an_option():
    args, _ = runner._build_send_keys_chain("pwa-x", text="-t pwa-other")
    assert args == [["send-keys", "-t", "pwa-x", "-l", "--", "-t pwa-other"]]


def test_a_trailing_semicolon_is_escaped_so_it_is_not_a_command_separator():
    args, _ = runner._build_send_keys_chain("pwa-x", text="a;")
    assert args == [["send-keys", "-t", "pwa-x", "-l", "--", "a\\;"]]


def test_the_enter_chain_still_uses_a_real_separator():
    args, chained = runner._build_send_keys_chain("pwa-x", text="a;", enter=True)
    assert chained is True
    assert args == [["send-keys", "-t", "pwa-x", "-l", "--", "a\\;", ";", "send-keys", "-t", "pwa-x", "Enter"]]


@pytest.mark.parametrize(
    ("text", "typed"),
    [
        ("a\r\nb", "a\nb"),
        ("a\rb", "a\nb"),
        ("a\r\n\r\nb", "a\n\nb"),
        ("a\tb\nc", "a\tb\nc"),
        ("a\x1bb\x03c\x00d\x7e", "abcd~"),
        ("日本語の文", "日本語の文"),
    ],
)
def test_line_ends_become_lf_and_other_control_characters_are_dropped(text, typed):
    assert runner._typed_text(text) == typed


def test_a_text_with_a_carriage_return_goes_the_multi_line_way(monkeypatch):
    loaded = []

    def fake_run(argv, **kwargs):
        loaded.append(kwargs.get("input"))
        return subprocess.CompletedProcess(argv, 0, b"", b"")

    monkeypatch.setattr(runner.subprocess, "run", fake_run)
    args, _ = runner._build_send_keys_chain("pwa-x", text="one\r\ntwo")
    assert loaded == [b"one\ntwo"]
    assert args[0][0] == "paste-buffer"


def test_a_text_of_control_characters_only_types_nothing():
    args, chained = runner._build_send_keys_chain("pwa-x", text="\x1b\x03")
    assert args == []
    assert chained is False


def test_a_key_name_is_still_passed_as_it_is():
    args, _ = runner._build_send_keys_chain("pwa-x", key="C-u")
    assert args == [["send-keys", "-t", "pwa-x", "C-u"]]


# --- through a real tmux -------------------------------------------------------------------------------------


@pytest.fixture
def pane(tmp_path, monkeypatch):
    """A private tmux pane that records what it receives; `received()` waits for the record and returns the bytes."""
    socket_name = f"cpc-send-text-{os.getpid()}-{time.monotonic_ns()}"
    out = tmp_path / "received.hex"
    program = tmp_path / "pane_program.py"
    program.write_text(_PANE_PROGRAM)
    session_id = "send_text"
    started = subprocess.run(
        [runner.TMUX_BIN, "-L", socket_name, "-f", "/dev/null", "new-session", "-d",
         "-s", runner._tmux_session_name(session_id), "-x", "120", "-y", "30",
         f"{sys.executable} -I {program} {out}"],
        capture_output=True, timeout=10,
    )
    assert started.returncode == 0, started.stderr
    socket_path = subprocess.run(
        [runner.TMUX_BIN, "-L", socket_name, "display-message", "-p", "#{socket_path}"],
        capture_output=True, timeout=10, text=True,
    ).stdout.strip()
    monkeypatch.setattr(runner, "TMUX_SOCKET_NAME", socket_name)
    monkeypatch.setattr(runner, "USE_TMUX_WRAP", True)
    deadline = time.monotonic() + READY_TIMEOUT_SEC
    while not Path(f"{out}.ready").exists():
        assert time.monotonic() < deadline, "the pane program did not start"
        time.sleep(0.02)

    def received() -> bytes:
        stop = time.monotonic() + RESULT_TIMEOUT_SEC
        while not out.exists():
            assert time.monotonic() < stop, "the pane program recorded nothing"
            time.sleep(0.02)
        return bytes.fromhex(out.read_text())

    yield session_id, received
    # The server ends with its only pane; tmux leaves the socket file behind.
    Path(socket_path).unlink(missing_ok=True)


@needs_tmux
@pytest.mark.parametrize(
    "text",
    [
        "an ordinary sentence",
        "-starts with a dash",
        "-t pwa-other -l",
        "--",
        "ends with a semicolon;",
        "two;;",
        ";",
        "ends with a backslash and a semicolon\\;",
        "a;b is not a separator",
        "日本語の文、そして末尾の句点。",
        "tab\tinside",
    ],
)
def test_the_text_arrives_character_for_character(pane, text):
    session_id, received = pane
    assert runner.tmux_send_keys(session_id, text=text) is True
    assert received() == text.encode("utf-8")


@needs_tmux
def test_a_trailing_semicolon_with_enter_types_the_text_then_enter(pane):
    session_id, received = pane
    assert runner.tmux_send_keys(session_id, text="done;", enter=True) is True
    assert received() == b"done;\r"


@needs_tmux
def test_control_characters_do_not_reach_the_pane(pane):
    session_id, received = pane
    assert runner.tmux_send_keys(session_id, text="a\x1b[31mb\x03c") is True
    assert received() == b"a[31mbc"


@needs_tmux
@pytest.mark.parametrize("line_end", ["\r\n", "\r", "\n"])
def test_every_kind_of_line_end_is_pasted_as_one_line_break(pane, line_end):
    session_id, received = pane
    assert runner.tmux_send_keys(session_id, text=f"first{line_end}second") is True
    assert received() == b"first\rsecond"
