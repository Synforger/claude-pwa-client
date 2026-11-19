"""What a conversation record says about work that a sleeping claude would lose: a wake-up it scheduled, a cron
job it created, a tool call that has no result yet; and when the conversation last did anything. Pure: it folds the
rows of a record one by one and touches no file; `sleep_sensors.py` reads the record and feeds the rows.

Used by the sleep judgement (`sleep_judgement.py`).
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from backend.fork.fork import is_limit_stop_row
from backend.jsonl.jsonl_predicates import (
    blocks_text,
    is_api_error_resume,
    is_continuable_error_row,
    is_meta,
    is_sidechain,
    is_user_prompt,
    queued_prompt_text,
)

SCHEDULE_WAKEUP = "ScheduleWakeup"
# The notices Claude Code writes as `system` rows (subtype `informational`) when a usage limit stops it and when the
# limit is over. The first books a continuation that Claude Code sends itself once the limit resets ("Usage limit
# reached · continuing automatically at 2am", or "... reached again ..."); the second says it is sending it now.
LIMIT_REACHED_NOTICE = "Usage limit reached"
LIMIT_RESET_NOTICE = "Usage limit reset"
# The kinds of `origin` of a prompt that settle the continuation a limit stop left owed: a person's words (or a message typed into the terminal)
# and the continuation Claude Code sends itself. A background task's notification does not.
SETTLING_ORIGINS = frozenset({"human", "auto-continuation"})
CRON_CREATE = "CronCreate"
CRON_DELETE = "CronDelete"


@dataclass(frozen=True)
class LimitStop:
    """A turn that a usage limit ended: the uuid of the row Claude Code wrote for it, and its time (unix seconds)."""
    uuid: str
    at: float


@dataclass(frozen=True)
class ErrorStop:
    """A turn that a passing API error ended (`jsonl_predicates.is_continuable_error_row`): the uuid and time (unix
    seconds) of the error row, its `error`, its cause (`apiError`, else `streamCutCause`, else empty) and the first line
    of its words."""
    uuid: str
    at: float
    error: str
    cause: str
    words: str


@dataclass
class RecordFacts:
    """The state the rows read so far leave behind.

    cron_open:            CronCreate calls not yet matched by a CronDelete (= session-only jobs, gone when claude exits)
    wakeup_pending:       a ScheduleWakeup was called after the last user prompt (= nothing delivered it yet)
    awaiting_tool_result: the last row of the conversation is a tool call that has no result yet (= claude waits for
                          an answer, a permission, or a tool that is still running)
    limit_stop:           the usage-limit stop the conversation ends in, None when it does not (= a limit row, the
                          API-error row or Claude Code's notice, is forgotten by any prompt or answer after it)
    continuation_owed:    the usage-limit stop whose continuation is still owed, None when there is none. Claude Code
                          books a continuation at a limit and sends it itself when the limit resets, but only the
                          claude that booked it does: a claude started again (moved to another account, put to sleep)
                          has lost it. It is settled by Claude Code's notice that the limit is over, a person's
                          prompt, or a message typed into the terminal; answers to background notifications in
                          between leave it owed
    error_stop:           the passing API error the conversation ends in, None when it does not (= any row of the
                          conversation after it, a prompt, an answer, a tool result, a hidden row or the mark of an
                          interruption, forgets it)
    error_streak:         how many turns in a row, counted back from the end, the client's message to carry on after
                          an API error (`backend/error_resume/`) started and a passing API error ended. A turn that
                          anything else started sets it back to 0. The answer a turn wrote before its error does not:
                          a reply cut off mid-way always writes its first part before the error, so a fault that keeps
                          cutting replies would otherwise never be counted
    error_turn_open:      the turn going on was started by that message and has not ended in an error yet
    last_row_at:          the time (unix seconds) of the newest row that carries one, None when no row does. This is
                          when the conversation last did anything: a running claude also rewrites its record without
                          adding a row, so the file's modification time says nothing about the conversation
    """
    cron_open: int = 0
    wakeup_pending: bool = False
    awaiting_tool_result: bool = False
    last_row_at: float | None = None
    limit_stop: LimitStop | None = None
    continuation_owed: LimitStop | None = None
    error_stop: ErrorStop | None = None
    error_streak: int = 0
    error_turn_open: bool = False

    @property
    def stopped_by_limit(self) -> bool:
        """Whether the conversation ends in a turn that a usage limit stopped."""
        return self.limit_stop is not None


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


def limit_notice_of(row: dict) -> str | None:
    """Which of Claude Code's limit notices `row` is (`LIMIT_REACHED_NOTICE` / `LIMIT_RESET_NOTICE`), None for any
    other row."""
    if row.get("type") != "system" or row.get("subtype") != "informational":
        return None
    content = row.get("content")
    if not isinstance(content, str):
        return None
    for notice in (LIMIT_REACHED_NOTICE, LIMIT_RESET_NOTICE):
        if content.startswith(notice):
            return notice
    return None


def settles_a_limit_stop(row: dict) -> bool:
    """Whether a user row settles the continuation a limit stop left owed: a prompt whose origin is a person, a message
    typed into the terminal or Claude Code's own continuation. A row with no origin counts when it is a prompt (= records written before Claude
    Code marked origins)."""
    origin = row.get("origin")
    if isinstance(origin, dict):
        return origin.get("kind") in SETTLING_ORIGINS
    return is_user_prompt(row)


def _open_limit_stop(facts: RecordFacts, row: dict, stamp: float | None) -> None:
    """Note the stop `row` opens. A stop already open is kept: Claude Code writes the API-error row and its notice for
    the same stop, and the first of them is when it began. The continuation owed is likewise the first stop's until it
    is settled (= "Usage limit reached again" is the same booking)."""
    stop = LimitStop(uuid=str(row.get("uuid") or ""), at=stamp if stamp is not None else 0.0)
    if facts.limit_stop is None:
        facts.limit_stop = stop
    if facts.continuation_owed is None:
        facts.continuation_owed = stop


def _error_stop_of(row: dict, stamp: float | None) -> ErrorStop:
    """The stop a passing API error row opens."""
    cause = row.get("apiError") or row.get("streamCutCause") or ""
    words = blocks_text((row.get("message") or {}).get("content")).strip().splitlines()
    return ErrorStop(uuid=str(row.get("uuid") or ""), at=stamp if stamp is not None else 0.0,
                     error=str(row.get("error") or ""), cause=str(cause), words=words[0] if words else "")


def _start_turn(facts: RecordFacts, text: str | None) -> None:
    """Note a prompt that starts a turn: the client's message to carry on after an API error keeps the streak and opens
    its turn, any other prompt sets the streak back."""
    facts.error_stop = None
    if is_api_error_resume(text):
        facts.error_turn_open = True
    else:
        facts.error_streak = 0
        facts.error_turn_open = False


def _prompt_text(row: dict) -> str | None:
    """The words of a user row that starts a turn someone gave (a prompt typed into the terminal, or the mark of an
    interruption); None for a tool result and a hidden row, which go on with the turn, and for a prompt Claude Code
    makes itself (a background task's notification), which gives no new work."""
    origin = row.get("origin")
    if is_meta(row) or isinstance(origin, dict) and origin.get("kind") != "human":
        return None
    content = (row.get("message") or {}).get("content")
    if isinstance(content, list) and any(isinstance(b, dict) and b.get("type") == "tool_result" for b in content):
        return None
    return blocks_text(content)


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
    if kind == "system":
        notice = limit_notice_of(row)
        if notice == LIMIT_REACHED_NOTICE:
            _open_limit_stop(facts, row, stamp)
        elif notice == LIMIT_RESET_NOTICE:
            facts.continuation_owed = None
        return
    if kind == "attachment":
        queued = queued_prompt_text(row)
        if queued is not None:
            _start_turn(facts, queued)
            facts.wakeup_pending = False
            facts.limit_stop = None
            facts.continuation_owed = None
        return
    if kind == "user":
        prompt = _prompt_text(row)
        if prompt is None:
            facts.error_stop = None
        else:
            _start_turn(facts, prompt)
        facts.awaiting_tool_result = False
        facts.limit_stop = None
        if settles_a_limit_stop(row):
            facts.continuation_owed = None
        if is_user_prompt(row):
            facts.wakeup_pending = False
        return
    if kind != "assistant":
        return
    if is_continuable_error_row(row):
        facts.awaiting_tool_result = False
        facts.limit_stop = None
        facts.error_stop = _error_stop_of(row, stamp)
        if facts.error_turn_open:
            facts.error_streak += 1
            facts.error_turn_open = False
        return
    facts.error_stop = None
    if is_limit_stop_row(row):
        facts.error_turn_open = False
        facts.error_streak = 0
        facts.awaiting_tool_result = False
        _open_limit_stop(facts, row, stamp)
        return
    facts.limit_stop = None
    names = _tool_names(row)
    facts.awaiting_tool_result = bool(names)
    for name in names:
        if name == SCHEDULE_WAKEUP:
            facts.wakeup_pending = True
        elif name == CRON_CREATE:
            facts.cron_open += 1
        elif name == CRON_DELETE:
            facts.cron_open = max(0, facts.cron_open - 1)
