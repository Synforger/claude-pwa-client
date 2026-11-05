"""What a conversation record says about work that a sleeping claude would lose: a wake-up it scheduled, a cron
job it created, a tool call that has no result yet; and when the conversation last did anything. Pure: it folds the
rows of a record one by one and touches no file; `sleep_sensors.py` reads the record and feeds the rows.

Used by the sleep judgement (`sleep_judgement.py`).
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from backend.jsonl.jsonl_predicates import is_sidechain, is_user_prompt, queued_prompt_text

SCHEDULE_WAKEUP = "ScheduleWakeup"
CRON_CREATE = "CronCreate"
CRON_DELETE = "CronDelete"


@dataclass
class RecordFacts:
    """The state the rows read so far leave behind.

    cron_open:            CronCreate calls not yet matched by a CronDelete (= session-only jobs, gone when claude exits)
    wakeup_pending:       a ScheduleWakeup was called after the last user prompt (= nothing delivered it yet)
    awaiting_tool_result: the last row of the conversation is a tool call that has no result yet (= claude waits for
                          an answer, a permission, or a tool that is still running)
    last_row_at:          the time (unix seconds) of the newest row that carries one, None when no row does. This is
                          when the conversation last did anything: a running claude also rewrites its record without
                          adding a row, so the file's modification time says nothing about the conversation
    """
    cron_open: int = 0
    wakeup_pending: bool = False
    awaiting_tool_result: bool = False
    last_row_at: float | None = None


def _tool_names(row: dict) -> list[str]:
    content = (row.get("message") or {}).get("content")
    if not isinstance(content, list):
        return []
    return [block.get("name") or "" for block in content if isinstance(block, dict) and block.get("type") == "tool_use"]


def row_time(row: dict) -> float | None:
    """The time a row carries (= its ISO `timestamp`), in unix seconds; None when it has none or it does not parse."""
    stamp = row.get("timestamp")
    if not isinstance(stamp, str):
        return None
    try:
        return datetime.fromisoformat(stamp).timestamp()
    except ValueError:
        return None


def fold_row(facts: RecordFacts, row: object) -> None:
    """Take one row of the record into `facts`. Every row with a time moves `last_row_at`; past that, rows of a
    sub-agent and rows that are not messages change nothing.

    A user prompt of any origin ends a pending wake-up (= it is what the wake-up delivers). A prompt that claude
    queued while it worked counts only when a person typed it: a background notification is not the wake-up."""
    if not isinstance(row, dict):
        return
    stamp = row_time(row)
    if stamp is not None and (facts.last_row_at is None or stamp > facts.last_row_at):
        facts.last_row_at = stamp
    if is_sidechain(row):
        return
    kind = row.get("type")
    if kind == "attachment":
        if queued_prompt_text(row) is not None:
            facts.wakeup_pending = False
        return
    if kind == "user":
        facts.awaiting_tool_result = False
        if is_user_prompt(row):
            facts.wakeup_pending = False
        return
    if kind != "assistant":
        return
    names = _tool_names(row)
    facts.awaiting_tool_result = bool(names)
    for name in names:
        if name == SCHEDULE_WAKEUP:
            facts.wakeup_pending = True
        elif name == CRON_CREATE:
            facts.cron_open += 1
        elif name == CRON_DELETE:
            facts.cron_open = max(0, facts.cron_open - 1)
