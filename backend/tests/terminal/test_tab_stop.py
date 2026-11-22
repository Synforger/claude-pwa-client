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


def _stand_in(monkeypatch, process: subprocess.Popen) -> list[tuple[str, bool]]:
    """Each removal of the tmux session, with whether the claude was gone by then."""
    calls: list[tuple[str, bool]] = []
    monkeypatch.setattr(tab_stop, "claude_pid_in_pane", lambda sid: process.pid)
    monkeypatch.setattr(tab_stop, "kill_tmux_session", lambda sid: calls.append((sid, process.poll() is not None)) or True)
    return calls


def test_a_claude_is_gone_before_its_tmux_session_is_removed(monkeypatch):
    process = _start("pass")
    calls = _stand_in(monkeypatch, process)
    assert tab_stop.stop_claude("ses_a") is True
    assert calls == [("ses_a", True)]
    process.stdout.close()


def test_a_claude_that_ignores_the_request_to_end_is_killed(monkeypatch):
    monkeypatch.setattr(tab_stop, "STOP_WAIT_SEC", 0.5)
    process = _start("signal.signal(signal.SIGTERM, signal.SIG_IGN)")
    calls = _stand_in(monkeypatch, process)
    assert tab_stop.stop_claude("ses_a") is True
    assert len(calls) == 1
    # it ignores the request and sleeps 60 s, so having ended means the kill reached it
    assert process.wait(timeout=1) is not None
    process.stdout.close()


def test_a_claude_that_stays_keeps_its_tmux_session_so_the_next_try_finds_it(monkeypatch):
    process = _start("pass")
    calls = _stand_in(monkeypatch, process)
    with monkeypatch.context() as stuck:
        stuck.setattr(tab_stop, "_wait_gone", lambda _process, _timeout: False)
        stuck.setattr(tab_stop.psutil.Process, "terminate", lambda self: None)
        stuck.setattr(tab_stop.psutil.Process, "kill", lambda self: None)
        assert tab_stop.stop_claude("ses_a") is False
        assert calls == []
    assert tab_stop.stop_claude("ses_a") is True
    assert len(calls) == 1
    process.stdout.close()


def test_a_claude_that_may_not_be_signalled_keeps_its_tmux_session(monkeypatch):
    process = _start("pass")
    calls = _stand_in(monkeypatch, process)

    def denied(self):
        raise tab_stop.psutil.AccessDenied(self.pid)
    with monkeypatch.context() as refused:
        refused.setattr(tab_stop.psutil.Process, "terminate", denied)
        assert tab_stop.stop_claude("ses_a") is False
    assert calls == []
    process.kill()
    process.wait(timeout=1)
    process.stdout.close()


def test_a_tab_without_a_claude_only_loses_its_tmux_session(monkeypatch):
    calls: list[str] = []
    monkeypatch.setattr(tab_stop, "claude_pid_in_pane", lambda sid: None)
    monkeypatch.setattr(tab_stop, "kill_tmux_session", lambda sid: calls.append(sid) or False)
    assert tab_stop.stop_claude("ses_a") is True
    assert calls == ["ses_a"]
