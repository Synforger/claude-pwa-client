"""Reads what the error resume needs about a tab and answers with `error_judgement.judge`. Blocking (the record, the
memo, the process table, the usage log); callers on the event loop run it in a thread.

The record is read first and alone: a tab whose conversation does not end in a passing API error (nearly every tab,
nearly every time) costs nothing more. A sleeping tab's record is the one its next start reopens.

Used by `error_patrol.py` and by the child watch (`child_watch/watch_sensors.py`), which keeps quiet about a child the
error resume holds.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

import backend.jsonl.jsonl_watcher as jsonl_watcher
from backend._common.state import SessionDef
from backend.account_fallback.fallback_sensors import read_tab_break
from backend.child_watch.child_memo import DONE, memo_state
from backend.child_watch.child_work import memo_of
from backend.error_resume.error_judgement import NONE, SEND, WAIT, judge
from backend.sleep.record_facts import ErrorStop, RecordFacts
from backend.sleep.sleep_sensors import record_facts_of
from backend.terminal.pty_discover import claude_pid_in_pane
from backend.terminal.session_resolver import takes_asks
from backend.usage.usage import read_all_rate_limits_tail

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ErrorLook:
    """What the error resume makes of a tab: its answer (`error_judgement`), the stop and streak it was judged on, and
    the time of the conversation's last row."""
    answer: str
    stop: ErrorStop | None = None
    streak: int = 0
    last_row_at: float | None = None


def _facts_of(meta: SessionDef) -> RecordFacts | None:
    """What the tab's record says; None when it has no record or it cannot be read."""
    record = Path(meta.sleep.record) if meta.sleep is not None else jsonl_watcher.get_jsonl_for(meta.id)
    if record is None:
        return None
    try:
        return record_facts_of(record)
    except OSError:
        logger.debug("error resume: a record could not be read: %s", record)
        return None


def _may_run(meta: SessionDef, rows: list[dict], now: float) -> bool:
    """Whether the tab may run now (`account_hold.hold_mail.may_run`). Imported here, as `limit_resume.resume_patrol`
    does: the account hold imports the account fallback, which sends its messages through the message route."""
    from backend.account_hold.hold_mail import may_run  # noqa: PLC0415
    from backend.account_hold.hold_settings import read_rules as read_hold_rules  # noqa: PLC0415
    return may_run(meta, rows, read_hold_rules(), now)


def look_at_tab(meta: SessionDef, now: float, rows: list[dict] | None = None) -> ErrorLook:
    """The error resume's answer for the tab. `rows` is the usage log's tail when the caller read it already (one read
    for a whole patrol); it is read here when needed and not given."""
    facts = _facts_of(meta)
    if facts is None or facts.error_stop is None:
        return ErrorLook(NONE)
    stop = facts.error_stop
    asleep = meta.sleep is not None
    claude_runs = not asleep and claude_pid_in_pane(meta.id) is not None
    answer = judge(
        stop=stop, streak=facts.error_streak, resumed=meta.error_resumed, gave_up=meta.error_gave_up,
        takes_asks=takes_asks(meta.id), reported=meta.child and memo_state(memo_of(meta)) == DONE,
        held=meta.held_at is not None,
        may_run=_may_run(meta, rows if rows is not None else read_all_rate_limits_tail(), now),
        owes_other=meta.owes_carry_on or bool(meta.kept_messages), asleep=asleep, claude_runs=claude_runs,
        at_break=claude_runs and read_tab_break(meta.id).at_break, now=now)
    return ErrorLook(answer, stop=stop, streak=facts.error_streak, last_row_at=facts.last_row_at)


def holds(meta: SessionDef, look: ErrorLook) -> bool:
    """Whether the error resume holds the tab's stop, so that the child watch keeps quiet about it: it is about to
    carry the tab on, or it gave up on this stop and told the parent itself."""
    if look.answer in (WAIT, SEND):
        return True
    return look.stop is not None and meta.error_gave_up == look.stop.uuid
