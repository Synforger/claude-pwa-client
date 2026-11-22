"""Whether a child tab is one the watch tells its parent about. Pure: it takes what was read and answers; it reads no
file, no process and no state.

A child is told about when it stopped without reporting: it is a working child (its memo has not been closed with a
report), its claude runs and is at a break (nothing is being answered, run in the back or scheduled), and that was seen
on two looks in a row at the same last row of its conversation. One stop is told once.

Used by `watch_sensors.py` and `watch_patrol.py`.
"""
from __future__ import annotations

from backend.child_watch.child_memo import WORKING

# Why the child stopped (= the `reason` of the message to the parent, and of the log line).
LIMIT = "limit"
IDLE = "idle"
# The error resume (`backend/error_resume/`) gave up carrying the child on after a passing API error. Only the error
# resume tells this one.
API_ERROR = "api_error"
# The child waits at a permission window that nobody answered for `PERMISSION_WAIT_SEC` (= `permission_window/window_state.py`).
PERMISSION = "permission"


def is_watched(*, child: bool, parent_known: bool, asleep: bool, memo_state: str) -> bool:
    """Whether the tab is looked at: a child of a tab that exists, awake, whose memo says it is still working (= a
    child that reported, or got stuck, has already told its parent; a sleeping child was put to sleep by its parent or
    by the sleep patrol)."""
    return child and parent_known and not asleep and memo_state == WORKING


def stop_reason(*, limit_stop: bool, continuation_owed: bool) -> str:
    """`LIMIT` when the record shows a usage limit (the stop it ends in, or a continuation Claude Code owes), else
    `IDLE` (= it waits at its prompt)."""
    return LIMIT if limit_stop or continuation_owed else IDLE


def permission_overdue(*, opened_at: float | None, now: float, wait_sec: float) -> bool:
    """Whether the window a child waits at has been open for `wait_sec` or longer (= `opened_at` None: it has none)."""
    return opened_at is not None and now - opened_at >= wait_sec


def should_tell(*, mark: float | None, previous: float | None, told: float | None) -> bool:
    """Whether to tell the parent now. `mark` is the time of the child's last row, seen while it is at a break (None =
    it is not at a break); `previous` the mark seen at the look before (None = it was not at a break then); `told` the
    mark the parent was already told about. Yes only when the same mark was seen on two looks in a row and not told."""
    return mark is not None and previous == mark and told != mark
