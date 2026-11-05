"""What makes a tab a tab that may be moved: the sleep judgement asked by hand, or a stop by a usage limit
(`account_fallback/fallback_sensors.py`)."""
from __future__ import annotations

import json

import pytest

import backend.account_fallback.fallback_sensors as sensors
from backend.sleep.record_facts import RecordFacts
from backend.sleep.sleep_judgement import SleepFacts
from backend.tests.limit_samples import lines_of, stopped_mid_turn


@pytest.fixture
def reads(monkeypatch, tmp_path):
    """The facts `gather` returns, and a record for the tab, are set by the test."""
    record = tmp_path / "tab.jsonl"
    record.write_text("\n".join(lines_of(stopped_mid_turn()[:3])) + "\n")
    state = {"facts": SleepFacts(), "asked": [], "voice": False, "rolling": False, "record": record}

    def _gather(session_id, minutes, by_hand=False):
        state["asked"].append((minutes, by_hand))
        return state["facts"]
    monkeypatch.setattr(sensors, "gather", _gather)
    monkeypatch.setattr(sensors.jsonl_watcher, "get_jsonl_for", lambda _sid: state["record"])
    monkeypatch.setattr(sensors, "claude_pid_in_pane", lambda _sid: 123)
    monkeypatch.setattr(sensors, "is_session_on_call", lambda _sid: state["voice"])
    monkeypatch.setattr(sensors.rollover, "asked", lambda _record: state["rolling"])
    return state


def test_the_break_is_the_sleep_judgement_asked_by_hand_so_the_quiet_minutes_are_not_waited(reads):
    reads["facts"] = SleepFacts(claude_running=True, quiet_minutes=0.2, record_found=True)
    assert sensors.read_tab_break("ses_x") == sensors.TabBreak(None, ())
    assert reads["asked"] == [(0, True)]


def test_the_line_of_the_automatic_rollover_is_not_looked_at(reads):
    reads["facts"] = SleepFacts(claude_running=True, context_pct=90, rollover_idle_pct=50)
    assert sensors.read_tab_break("ses_x").at_break


@pytest.mark.parametrize("facts, reason", [
    (SleepFacts(claude_running=True, turn_open=True), "turn_open"),                       # it is answering
    (SleepFacts(claude_running=True, foreign_processes=("sleep",)), "processes_running"),  # a command in the back
    (SleepFacts(claude_running=True, record=RecordFacts(awaiting_tool_result=True)), "awaiting_tool_result"),
    (SleepFacts(claude_running=True, record=RecordFacts(wakeup_pending=True)), "wakeup_scheduled"),
    (SleepFacts(claude_running=True, record=RecordFacts(cron_open=1)), "cron_scheduled"),
    (SleepFacts(claude_running=True, on_voice_call=True), "voice_call"),
    (SleepFacts(claude_running=True, rolling_over=True), "rolling_over"),
])
def test_a_tab_in_the_middle_of_something_is_not_at_a_break(reads, facts, reason):
    reads["facts"] = facts
    tab_break = sensors.read_tab_break("ses_x")
    assert tab_break.blocked_by == (reason,) and not tab_break.at_break


def _stopped_record(reads, tmp_path):
    record = tmp_path / "stopped.jsonl"
    record.write_text("\n".join(lines_of(stopped_mid_turn())) + "\n")
    reads["record"] = record


def test_a_stop_by_the_limit_is_a_break_whatever_the_turn_and_the_commands_were(reads, tmp_path):
    _stopped_record(reads, tmp_path)
    reads["facts"] = SleepFacts(claude_running=True, turn_open=True, foreign_processes=("sleep",))
    tab_break = sensors.read_tab_break("ses_x")
    assert tab_break.at_break and tab_break.stop.uuid == "lim1"
    assert reads["asked"] == []                         # the stop is the break: nothing else is gathered


@pytest.mark.parametrize("hold, reason", [("voice", "voice_call"), ("rolling", "rolling_over")])
def test_a_voice_call_or_a_rollover_in_progress_still_holds_a_tab_the_limit_stopped(reads, tmp_path, hold, reason):
    _stopped_record(reads, tmp_path)
    reads[hold] = True
    assert sensors.read_tab_break("ses_x").blocked_by == (reason,)


def test_a_conversation_that_went_on_after_the_limit_row_is_not_a_stop(reads, tmp_path):
    record = tmp_path / "went-on.jsonl"
    rows = [*stopped_mid_turn(), {"type": "user", "uuid": "u9", "parentUuid": "lim1", "origin": {"kind": "human"},
                                  "message": {"content": "go on"}}]
    record.write_text("\n".join(json.dumps(r) for r in rows) + "\n")
    reads["record"] = record
    assert sensors.read_tab_break("ses_x").stop is None
