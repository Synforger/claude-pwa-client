"""Whether a process runs under another claude (`backend/terminal/pty_discover.py::runs_inside_another_claude`)."""
from __future__ import annotations

import psutil

from backend.terminal import pty_discover


class _Proc:
    def __init__(self, name: str, argv0: str | None = None):
        self._name, self._argv0 = name, argv0 or name

    def name(self) -> str:
        return self._name

    def cmdline(self) -> list[str]:
        return [self._argv0]


def _with_parents(monkeypatch, *parents: _Proc) -> None:
    class _Child:
        def __init__(self, pid):
            pass

        def parents(self):
            return list(parents)

    monkeypatch.setattr(pty_discover.psutil, "Process", _Child)


def test_a_claude_with_a_claude_above_it_runs_inside_another(monkeypatch):
    _with_parents(monkeypatch, _Proc("zsh"), _Proc("2.1.330", "claude"), _Proc("tmux"))
    assert pty_discover.runs_inside_another_claude(1) is True


def test_the_tabs_own_claude_has_none_above_it(monkeypatch):
    _with_parents(monkeypatch, _Proc("zsh"), _Proc("python3"), _Proc("tmux"), _Proc("launchd"))
    assert pty_discover.runs_inside_another_claude(1) is False


def test_a_process_that_is_gone_is_not_inside_another(monkeypatch):
    def gone(pid):
        raise psutil.NoSuchProcess(pid)
    monkeypatch.setattr(pty_discover.psutil, "Process", gone)
    assert pty_discover.runs_inside_another_claude(1) is False
