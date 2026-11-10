"""When a tab may sleep (`sleep/sleep_judgement.py`): every condition must hold, and each one that fails is named."""
from __future__ import annotations

import dataclasses

import pytest

from backend.sleep import sleep_judgement as j
from backend.sleep.record_facts import RecordFacts

MINUTES = 60

READY = j.SleepFacts(
    claude_running=True, starting=False, turn_open=False, record_found=True, quiet_minutes=61.0, context_pct=20,
    rollover_idle_pct=40, foreign_processes=(), record=RecordFacts(), on_voice_call=False, rolling_over=False,
)


def test_a_quiet_tab_with_nothing_running_may_sleep():
    assert j.judge(READY, MINUTES) == ()


def test_a_tab_that_just_reached_the_quiet_time_may_sleep():
    assert j.judge(dataclasses.replace(READY, quiet_minutes=60.0), MINUTES) == ()


def test_an_agent_without_a_rollover_line_has_no_context_condition():
    assert j.judge(dataclasses.replace(READY, context_pct=99, rollover_idle_pct=None), MINUTES) == ()


# One case per condition: the only thing that differs from READY is the one fact that breaks it.
@pytest.mark.parametrize("change, reason", [
    ({"claude_running": False}, j.CLAUDE_NOT_RUNNING),
    ({"starting": True}, j.STARTING),
    ({"turn_open": True}, j.TURN_OPEN),
    ({"record_found": False, "quiet_minutes": None}, j.NO_RECORD),
    ({"quiet_minutes": 59.9}, j.NOT_QUIET),
    ({"context_pct": 40}, j.CONTEXT_AT_ROLLOVER_LINE),
    ({"context_pct": 75}, j.CONTEXT_AT_ROLLOVER_LINE),
    ({"foreign_processes": ("caffeinate",)}, j.PROCESSES_RUNNING),
    ({"foreign_processes": ("zsh", "python3")}, j.PROCESSES_RUNNING),
    ({"record": RecordFacts(wakeup_pending=True)}, j.WAKEUP_SCHEDULED),
    ({"record": RecordFacts(cron_open=1)}, j.CRON_SCHEDULED),
    ({"record": RecordFacts(awaiting_tool_result=True)}, j.AWAITING_TOOL_RESULT),
    ({"on_voice_call": True}, j.VOICE_CALL),
    ({"rolling_over": True}, j.ROLLING_OVER),
])
def test_a_tab_is_left_awake_when_one_condition_fails(change, reason):
    assert j.judge(dataclasses.replace(READY, **change), MINUTES) == (reason,)


def test_every_condition_that_fails_is_named():
    facts = dataclasses.replace(READY, turn_open=True, quiet_minutes=3.0, foreign_processes=("node",))
    assert j.judge(facts, MINUTES) == (j.TURN_OPEN, j.NOT_QUIET, j.PROCESSES_RUNNING)


def test_a_fact_that_was_not_read_is_skipped_not_failed():
    assert j.judge(j.SleepFacts(claude_running=True, starting=False), MINUTES) == ()
    assert j.judge(j.SleepFacts(claude_running=False), MINUTES) == (j.CLAUDE_NOT_RUNNING,)


# --- the processes under a claude ---


def _node(*names: str, children: tuple = ()) -> j.ProcessNode:
    return j.ProcessNode(names=names, children=children)


@pytest.mark.parametrize("tool", sorted(j.LANGUAGE_TOOLS))
def test_a_language_tool_does_not_count_as_work(tool):
    assert j.foreign_processes((_node(tool),)) == ()


def test_a_language_tool_run_by_node_is_known_by_its_arguments():
    assert j.foreign_processes((_node("node", "typescript-language-server"),)) == ()


def test_nothing_below_a_language_tool_is_looked_at():
    tsserver = _node("node", "tsserver.js")
    assert j.foreign_processes((_node("node", "typescript-language-server", children=(tsserver,)),)) == ()


def test_caffeinate_and_commands_count_as_work():
    tree = (_node("caffeinate"), _node("zsh", children=(_node("python3"),)), _node("clangd"))
    assert j.foreign_processes(tree) == ("caffeinate", "zsh", "python3")


def test_a_process_with_no_readable_name_counts_as_work():
    assert j.foreign_processes((_node("?"),)) == ("?",)


def test_a_sleep_by_hand_does_not_wait_for_the_quiet_time_nor_stop_at_the_rollover_line():
    facts = dataclasses.replace(READY, quiet_minutes=1.0, context_pct=55)
    assert j.judge(facts, MINUTES) == (j.NOT_QUIET, j.CONTEXT_AT_ROLLOVER_LINE)
    assert j.judge(facts, MINUTES, by_hand=True) == ()


def test_a_sleep_by_hand_keeps_every_other_condition():
    facts = dataclasses.replace(READY, quiet_minutes=1.0, turn_open=True, on_voice_call=True,
                                record=RecordFacts(wakeup_pending=True))
    assert j.judge(facts, MINUTES, by_hand=True) == (j.TURN_OPEN, j.WAKEUP_SCHEDULED, j.VOICE_CALL)


def test_a_tab_a_limit_stopped_is_not_held_by_what_the_stop_leaves_looking_like_work():
    facts = dataclasses.replace(READY, starting=True, turn_open=True, record=RecordFacts(awaiting_tool_result=True))
    assert j.judge(facts, MINUTES) == (j.STARTING, j.TURN_OPEN, j.AWAITING_TOOL_RESULT)
    assert j.judge(facts, MINUTES, stopped_by_limit=True) == ()


def test_a_tab_a_limit_stopped_is_still_held_by_what_really_runs_under_it():
    facts = dataclasses.replace(READY, claude_running=False, foreign_processes=("sleep",), on_voice_call=True,
                                rolling_over=True, record=RecordFacts(wakeup_pending=True, cron_open=1))
    assert j.judge(facts, MINUTES, stopped_by_limit=True) == (
        j.CLAUDE_NOT_RUNNING, j.PROCESSES_RUNNING, j.WAKEUP_SCHEDULED, j.CRON_SCHEDULED, j.VOICE_CALL, j.ROLLING_OVER)


def test_the_two_options_add_up():
    facts = dataclasses.replace(READY, quiet_minutes=1.0, turn_open=True)
    assert j.judge(facts, MINUTES, by_hand=True, stopped_by_limit=True) == ()


# A child that reported its work done.
REPORTED = dataclasses.replace(READY, quiet_minutes=j.REPORTED_QUIET_MINUTES, answered_since_start=True,
                               account_pending=False)


def test_a_reported_child_quiet_for_a_few_minutes_may_sleep_even_above_the_rollover_line():
    assert j.judge(dataclasses.replace(REPORTED, context_pct=80), j.REPORTED_QUIET_MINUTES, reported=True) == ()


def test_a_reported_child_that_has_not_answered_since_it_started_stays_awake():
    facts = dataclasses.replace(REPORTED, answered_since_start=False)
    assert j.judge(facts, j.REPORTED_QUIET_MINUTES, reported=True) == (j.NOT_ANSWERED_SINCE_START,)


def test_a_reported_child_still_writing_stays_awake():
    facts = dataclasses.replace(REPORTED, quiet_minutes=j.REPORTED_QUIET_MINUTES - 0.5)
    assert j.judge(facts, j.REPORTED_QUIET_MINUTES, reported=True) == (j.NOT_QUIET,)


def test_a_reported_child_stopped_by_a_limit_may_sleep_at_that_stop():
    facts = dataclasses.replace(REPORTED, turn_open=True, record=RecordFacts(awaiting_tool_result=True))
    assert j.judge(facts, j.REPORTED_QUIET_MINUTES, stopped_by_limit=True, reported=True) == ()


def test_a_tab_the_account_features_wait_on_is_left_to_them_by_the_patrol_but_not_by_hand():
    facts = dataclasses.replace(READY, account_pending=True)
    assert j.judge(facts, MINUTES) == (j.ACCOUNT_PENDING,)
    assert j.judge(dataclasses.replace(REPORTED, account_pending=True), j.REPORTED_QUIET_MINUTES,
                   reported=True) == (j.ACCOUNT_PENDING,)
    assert j.judge(facts, 0, by_hand=True) == ()


@pytest.mark.parametrize("previous, level, short", [
    (2, 2, True), (4, 2, True), (1, 2, False), (2, 1, False), (None, 4, False), (4, None, False), (1, 1, False),
])
def test_the_machine_is_short_of_memory_only_on_two_high_readings_in_a_row(previous, level, short):
    assert j.is_short_of_memory(previous, level) is short


def test_under_pressure_the_tab_quiet_the_longest_is_chosen():
    assert j.pick_under_pressure([("a", 12.0), ("b", 40.0), ("c", 11.0)]) == "b"
    assert j.pick_under_pressure([]) is None
