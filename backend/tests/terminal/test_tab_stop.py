"""Stopping a tab's claude (`terminal/tab_stop.py`): the next claude starts only once the previous one has ended."""
from __future__ import annotations

import subprocess
import sys

from backend.terminal import tab_stop


def _start(script: str) -> subprocess.Popen:
    """A process standing in for a tab's claude, running `script`; returns once it runs."""
    process = subprocess.Popen([sys.executable, "-c", f"import signal, time; {script}; print(flush=True); time.sleep(60)"],
                               stdout=subprocess.PIPE)
    process.stdout.readline()
    return process


def _stand_in(monkeypatch, process: subprocess.Popen, *, hang_up: bool) -> list[str]:
    calls: list[str] = []
    monkeypatch.setattr(tab_stop, "claude_pid_in_pane", lambda sid: process.pid)

    def kill_session(sid: str) -> bool:
        calls.append(f"kill-session {sid}")
        if hang_up:
            process.send_signal(subprocess.signal.SIGHUP)
        return True
    monkeypatch.setattr(tab_stop, "kill_tmux_session", kill_session)
    return calls


def test_a_claude_that_ends_on_the_hang_up_is_waited_for(monkeypatch):
    process = _start("pass")
    calls = _stand_in(monkeypatch, process, hang_up=True)
    assert tab_stop.stop_claude("ses_a") is True
    assert calls == ["kill-session ses_a"]
    assert process.wait(timeout=1) is not None
    process.stdout.close()


def test_a_claude_that_ignores_the_hang_up_is_killed(monkeypatch):
    monkeypatch.setattr(tab_stop, "STOP_WAIT_SEC", 0.5)
    process = _start("signal.signal(signal.SIGHUP, signal.SIG_IGN)")
    _stand_in(monkeypatch, process, hang_up=True)
    assert tab_stop.stop_claude("ses_a") is True
    # it ignores the hang-up and sleeps 60 s, so having ended means the kill reached it
    assert process.wait(timeout=1) is not None
    process.stdout.close()


def test_a_tab_without_a_claude_only_loses_its_tmux_session(monkeypatch):
    calls: list[str] = []
    monkeypatch.setattr(tab_stop, "claude_pid_in_pane", lambda sid: None)
    monkeypatch.setattr(tab_stop, "kill_tmux_session", lambda sid: calls.append(sid) or False)
    assert tab_stop.stop_claude("ses_a") is True
    assert calls == ["ses_a"]
