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
