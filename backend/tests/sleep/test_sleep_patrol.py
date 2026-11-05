"""A tab seen awake again starts its quiet time over (`sleep/sleep_patrol.py`)."""
from __future__ import annotations

import time

import backend.sleep.sleep_patrol as patrol
import backend.sleep.sleep_sensors as sensors
from backend._common.state import SleepMark, register_session
from backend.tests.async_run import run


def _asleep(isolated_state):
    tab = register_session("agent_a", title="T")
    tab.sleep = SleepMark(claude_sid="abc", record="/nonexistent/abc.jsonl", slept_at=int(time.time()) - 3600)
    return tab


def test_a_tab_whose_claude_runs_again_loses_its_mark_and_its_quiet_time_starts_over(isolated_state, monkeypatch):
    tab = _asleep(isolated_state)
    monkeypatch.setattr(patrol.input_ready, "is_ready", lambda _sid: True)
    monkeypatch.setattr(patrol, "claude_pid_in_pane", lambda _sid: 4242)
    monkeypatch.setattr(patrol.jsonl_watcher, "get_jsonl_for", lambda _sid: None)
    sensors._woken_at.pop(tab.id, None)
    before = time.time()
    run(patrol._clear_when_awake(tab))
    try:
        assert tab.sleep is None
        assert before <= sensors._woken_at[tab.id] <= time.time()
    finally:
        sensors._woken_at.pop(tab.id, None)


def test_a_tab_whose_claude_has_not_come_up_keeps_its_mark_and_has_no_wake_time(isolated_state, monkeypatch):
    tab = _asleep(isolated_state)
    monkeypatch.setattr(patrol.input_ready, "is_ready", lambda _sid: True)
    monkeypatch.setattr(patrol, "claude_pid_in_pane", lambda _sid: None)
    sensors._woken_at.pop(tab.id, None)
    run(patrol._clear_when_awake(tab))
    assert tab.sleep is not None and tab.id not in sensors._woken_at
