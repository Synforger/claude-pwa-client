"""`tabs capacity`: what it asks the backend and how it prints the answer."""
from __future__ import annotations

import json

from backend.cli import capacity

VIEW = {"machine": "company", "child_sessions_max": None, "children_of_caller": 1,
        "tabs": {"total": 4, "with_claude": 2, "asleep": 1, "without_claude": 1, "children": 1},
        "claude_mb": {"count": 2, "median": 250.0, "min": 240.0, "max": 260.0, "total": 500.0},
        "memory": {"total_mb": 32768.0, "available_mb": 5120.0, "pressure_level": 1, "swap_used_mb": 1024.0},
        "claudes_fitting_available": 20,
        "accounts": [{"id": "work", "usage": {"five_hour_pct": 11, "five_hour_resets_at": None, "seven_day_pct": 87,
                                             "seven_day_resets_at": None}, "tabs_with_claude": 2},
                     {"id": "personal", "usage": None, "tabs_with_claude": 0}]}


class _Calls:
    def __init__(self, status=200, body=None) -> None:
        self.status, self.body, self.made = status, VIEW if body is None else body, []

    def __call__(self, path, form=None, method=None, timeout=None):
        self.made.append(path)
        return self.status, self.body


def test_the_asking_tab_is_named_so_its_children_are_counted(monkeypatch, capsys):
    monkeypatch.setenv("PWA_SID", "ses_a")
    calls = _Calls()
    assert capacity.run([], calls) == 0
    assert calls.made == ["/capacity?session=ses_a"]
    printed = capsys.readouterr().out
    assert "machine company: child tabs no limit (this tab has 1)" in printed
    assert "tabs 4: claude running 2, asleep 1, no claude 1 (children 1)" in printed
    assert "memory: 5.0 GB available of 32.0 GB, pressure 1 (normal), swap 1.0 GB used" in printed
    assert "a running claude takes 250 MB (median of 2; 240-260 MB), so the available memory holds about 20 more" in printed
    assert "account work: 5h 11% (resets ?), 7d 87% (resets ?); claude running 2" in printed
    assert "account personal: no usage yet; claude running 0" in printed


def test_json_prints_the_backends_answer(monkeypatch, capsys):
    monkeypatch.delenv("PWA_SID", raising=False)
    calls = _Calls()
    assert capacity.run(["--json"], calls) == 0
    assert calls.made == ["/capacity"] and json.loads(capsys.readouterr().out) == VIEW


def test_a_refusal_is_printed_and_ends_with_1(capsys):
    calls = _Calls(403, {"detail": {"code": "capacity_local_only", "message": "this machine only"}})
    assert capacity.run([], calls) == 1
    assert "this machine only" in capsys.readouterr().err


def test_other_words_print_the_usage():
    assert capacity.run(["--all"], _Calls()) == 2
