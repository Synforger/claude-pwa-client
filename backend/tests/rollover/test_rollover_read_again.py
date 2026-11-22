"""The watch of the automatic rollover reads a quiet tab again just before it types: one that moved while the watch
looked is passed over, and nothing of that look stays. The fakes are those of `test_rollover.py`.
"""
from __future__ import annotations

import pytest

import backend.rollover.rollover as watch
from backend.sleep.sleep_judgement import SleepFacts
from backend.tests.rollover.test_rollover import Tabs, _asked_once, _fresh_memory  # noqa: F401 (an autouse fixture)


@pytest.fixture
def tabs(monkeypatch, tmp_path, isolated_state) -> Tabs:
    return Tabs(monkeypatch, tmp_path, isolated_state)


def _during_the_look(tabs, monkeypatch, change):
    """`change` happens to `ses_a` while the watch looks at its pane."""

    def look(sid):
        if sid == "ses_a":
            change()
        return sid not in tabs.absent

    monkeypatch.setattr(watch, "claude_in_pane", look)


@pytest.mark.parametrize("change", ["busy", "started", "written"])
def test_a_quiet_tab_that_moved_during_the_look_is_passed_over(tabs, monkeypatch, change):
    monkeypatch.setattr(watch, "_started", set())
    tabs.add("ses_a", pct=45, idle_minutes=90)
    tabs.add("ses_b", pct=45, idle_minutes=60)
    changes = {"busy": lambda: tabs.busy.update(ses_a=True), "started": lambda: watch._started.add("ses_a"),
               "written": lambda: tabs.quiet_for("ses_a", 0)}
    _during_the_look(tabs, monkeypatch, changes[change])
    assert tabs.tick() == "ses_b"                              # the next one is asked
    assert [sid for sid, _ in tabs.asks()] == ["ses_b"]
    assert str(tabs.records["ses_a"]) not in watch._asked_at   # and the one passed over starts no gap


def test_a_tab_over_the_working_line_is_asked_though_it_began_a_turn(tabs, monkeypatch):
    tabs.add("ses_a", pct=70, idle_minutes=3)
    _during_the_look(tabs, monkeypatch, lambda: tabs.busy.update(ses_a=True))
    assert tabs.tick() == "ses_a"


def test_a_stalled_close_is_not_typed_again_into_a_turn_that_began(tabs, monkeypatch):
    _asked_once(tabs, "ses_a", quiet=40)
    tabs.close["ses_a"] = (True, False, SleepFacts(rollover_asks=1, quiet_minutes=41))
    _during_the_look(tabs, monkeypatch, lambda: tabs.busy.update(ses_a=True))
    assert tabs.tick() is None and tabs.asks() == []
