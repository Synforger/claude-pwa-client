"""What the rows of a conversation record say about work a sleeping claude would lose (`sleep/record_facts.py`)."""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from backend.sleep.record_facts import RecordFacts, fold_row


def _prompt(text: str = "go on") -> dict:
    return {"type": "user", "origin": {"kind": "human"}, "message": {"content": text}}


def _result() -> dict:
    return {"type": "user", "message": {"content": [{"type": "tool_result", "tool_use_id": "t", "content": "ok"}]}}


def _call(name: str) -> dict:
    return {"type": "assistant", "message": {"content": [{"type": "tool_use", "id": "t", "name": name, "input": {}}]}}


def _said(text: str = "done") -> dict:
    return {"type": "assistant", "message": {"content": [{"type": "text", "text": text}]}}


def _queued(origin_kind: str) -> dict:
    return {"type": "attachment", "attachment": {"type": "queued_command", "commandMode": "prompt",
                                                  "origin": {"kind": origin_kind}, "prompt": "later"}}


def _fold(*rows: object) -> RecordFacts:
    facts = RecordFacts()
    for row in rows:
        fold_row(facts, row)
    return facts


def test_a_finished_turn_leaves_nothing_behind():
    assert _fold(_prompt(), _call("Bash"), _result(), _said()) == RecordFacts()


def test_a_tool_call_without_a_result_means_claude_waits():
    assert _fold(_prompt(), _call("Bash")).awaiting_tool_result is True
    assert _fold(_prompt(), _call("Bash"), _result()).awaiting_tool_result is False


def test_a_wakeup_called_after_the_last_prompt_stays_pending():
    facts = _fold(_prompt(), _call("ScheduleWakeup"), _result(), _said())
    assert facts.wakeup_pending is True
    assert facts.awaiting_tool_result is False


def test_the_prompt_a_wakeup_delivers_ends_it():
    assert _fold(_call("ScheduleWakeup"), _result(), _said(), _prompt("tick")).wakeup_pending is False


def test_a_wakeup_called_again_after_the_delivery_is_pending_again():
    facts = _fold(_call("ScheduleWakeup"), _result(), _prompt("tick"), _call("ScheduleWakeup"), _result(), _said())
    assert facts.wakeup_pending is True


def test_a_prompt_a_person_queued_ends_a_wakeup_but_a_notification_does_not():
    assert _fold(_call("ScheduleWakeup"), _queued("human")).wakeup_pending is False
    assert _fold(_call("ScheduleWakeup"), _queued("task-notification")).wakeup_pending is True


def test_cron_jobs_count_until_deleted():
    assert _fold(_call("CronCreate"), _result()).cron_open == 1
    assert _fold(_call("CronCreate"), _call("CronCreate"), _call("CronDelete")).cron_open == 1
    assert _fold(_call("CronCreate"), _call("CronDelete")).cron_open == 0
    assert _fold(_call("CronDelete")).cron_open == 0      # a delete of a job this record never created


def test_a_cron_job_survives_later_prompts():
    assert _fold(_call("CronCreate"), _result(), _prompt(), _said()).cron_open == 1


@pytest.mark.parametrize("row", [None, "text", 3, [], {"type": "system"}, {"type": "summary"}, {"type": "assistant"}])
def test_rows_that_are_not_messages_change_nothing(row):
    facts = _fold(_call("ScheduleWakeup"), _result())
    before = RecordFacts(facts.cron_open, facts.wakeup_pending, facts.awaiting_tool_result)
    fold_row(facts, row)
    assert facts.cron_open == before.cron_open and facts.wakeup_pending == before.wakeup_pending


def test_the_rows_of_a_sub_agent_are_not_the_conversation():
    side = {**_call("ScheduleWakeup"), "isSidechain": True}
    assert _fold(side) == RecordFacts()


def test_the_newest_row_time_is_kept_whatever_the_row():
    facts = RecordFacts()
    for row in ({"type": "user", "timestamp": "2026-11-05T03:58:29.000Z", "message": {"content": "go"}},
                {"type": "assistant", "isSidechain": True, "timestamp": "2026-11-05T04:00:00Z"},
                {"type": "system", "timestamp": "2026-11-05T03:59:00Z"},
                {"type": "ai-title"},
                {"type": "user", "timestamp": "not a time"}):
        fold_row(facts, row)
    assert facts.last_row_at == datetime(2026, 11, 5, 4, 0, tzinfo=timezone.utc).timestamp()
