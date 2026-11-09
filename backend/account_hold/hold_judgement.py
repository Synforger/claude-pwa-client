"""Whether the account hold stops the tabs of an account, and whether a tab is asked to come to a break first. Pure: it
takes the facts and answers, and reads no file, no log and no state.

The usage of the 7 days of an account is judged by `usage.limit_state` against the line the rule names for the day of the
week (`hold_line_pct`); the 5 hours never count here. A tab may be stopped only at a break (which the account fallback's
`read_tab_break` reads); a tab that keeps answering is asked once to come to one (`should_ask_to_hold`).

Used by `hold_patrol.py` and `hold_continue.py`.
"""
from __future__ import annotations

from datetime import datetime
from typing import Iterable

from backend.account_fallback.fallback_settings import AT_PCT_MAX, WEEKDAYS
from backend.account_hold.hold_settings import HoldRule
from backend.sleep.sleep_judgement import TURN_OPEN
from backend.usage.limit_state import limit_state

# A percentage no usage of the 5 hours reaches, so that `limit_state` counts only the 7 days.
NO_FIVE_HOUR_LINE_PCT = AT_PCT_MAX + 1


def hold_line_pct(rule: HoldRule, now: float) -> int | None:
    """The line of the 7 days at time `now`: the one `rule` names for that day of the week (by the local time of this
    machine, so it changes at 0:00), None when it names none (= the day has no line)."""
    return rule.seven_day_at_pct.get(WEEKDAYS[datetime.fromtimestamp(now).weekday()])


def is_over_line(rows: Iterable[dict], rule: HoldRule | None, now: float) -> bool | None:
    """Whether the 7 days of the account of `rule` are at the line of today or more and not reset. False for a day
    without a line (or no rule), None when the log says nothing about the account."""
    line = hold_line_pct(rule, now) if rule is not None else None
    if rule is None or line is None:
        return False
    state = limit_state(rows, rule.account, NO_FIVE_HOUR_LINE_PCT, now, seven_day_line_pct=line)
    return None if state is None else state.at_limit


def should_ask_to_hold(*, blocked_by: tuple[str, ...], stopped_by_limit: bool, asked_at: float | None) -> bool:
    """Whether the tab is asked to come to a break: it is held because claude is answering (`turn_open` among
    `blocked_by`; a tab held only by commands, wake-ups or a call is not answering), no usage limit stopped it (that
    stop is its break) and it was not asked during this stay above the line (`asked_at` = None)."""
    return TURN_OPEN in blocked_by and not stopped_by_limit and asked_at is None
