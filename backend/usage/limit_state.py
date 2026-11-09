"""Whether an account is at its usage limit, and when that ends. Pure: it reads the rows of the rate-limit log it is
given (`usage.read_all_rate_limits_tail`) and the time it is told, and touches no file.

A window (the 5 hours, the 7 days) is at the limit when its usage is at or above the line and its reset time has not
passed. Used by the account fallback (`account_fallback/fallback_judgement.py`) and by the limit resume
(`limit_resume/resume_judgement.py`), which differ in the line they ask about. The 7 days may be asked about against a
line of their own.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

# The accounts a log row without an `account_id` belongs to (= what `usage.latest_from_tail` assumes).
UNNAMED_ROW_ACCOUNT = "personal"
# The windows the log reports: (usage percentage, reset time) fields of a row.
WINDOWS = (("five_hour_pct", "five_hour_resets_at"), ("seven_day_pct", "seven_day_resets_at"))


@dataclass(frozen=True)
class LimitState:
    """What the newest row of an account says about the line it was asked about.

    at_limit:   some window is at or above the line and has not reset yet
    read_at:    when the row was written (unix seconds), None when the row carries no time
    ends_at:    when the last of the windows at the limit resets (unix seconds), None when the account is not at the
                limit or the row gives no reset time
    last_reset: the latest reset time (unix seconds) that has passed among the windows at or above the line (= the row is
                from before that window reset, and no later row replaced it), None when there is none
    """
    at_limit: bool
    read_at: float | None
    ends_at: float | None
    last_reset: float | None


def latest_account_row(rows: Iterable[dict], account_id: str) -> dict | None:
    """The newest row of `account_id` (= the last one, the log is in time order), None when it has none."""
    found = None
    for row in rows:
        if (row.get("account_id") or UNNAMED_ROW_ACCOUNT) == account_id:
            found = row
    return found


def _number(value: object) -> float | None:
    return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else None


def limit_state(rows: Iterable[dict], account_id: str, line_pct: float, now: float, *,
                seven_day_line_pct: float | None = None) -> LimitState | None:
    """The state of `account_id` against `line_pct` (= a percentage) at time `now`. `seven_day_line_pct` is the line of
    the 7 days when it differs from the 5 hours' (= without it `line_pct` is both). None when the log has no row of
    the account or its newest row has no usage figure, since nothing can be said then."""
    row = latest_account_row(rows, account_id)
    if row is None:
        return None
    at_limit = False
    ends: list[float] = []
    resets_passed: list[float] = []
    known = False
    lines = (line_pct, line_pct if seven_day_line_pct is None else seven_day_line_pct)
    for (pct_field, reset_field), line in zip(WINDOWS, lines):
        pct = _number(row.get(pct_field))
        if pct is None:
            continue
        known = True
        if pct < line:
            continue
        resets_at = _number(row.get(reset_field))
        if resets_at is not None and resets_at <= now:
            resets_passed.append(resets_at)
            continue
        at_limit = True
        if resets_at is not None:
            ends.append(resets_at)
    if not known:
        return None
    return LimitState(at_limit=at_limit, read_at=_number(row.get("timestamp")),
                      ends_at=max(ends) if at_limit and ends else None,
                      last_reset=max(resets_passed) if resets_passed else None)
