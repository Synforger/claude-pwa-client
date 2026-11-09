"""Whether the account hold stops the tabs of an account, and whether a tab is asked to come to a break first. Pure: it
takes the facts and answers, and reads no file, no log and no state.

The usage of an account is judged by `usage.limit_state` against the line the rule names for the day of the week for
its 7 days (`hold_line_pct`) and against its `five_hour_at_pct` for its 5 hours; a window the rule names no line for
never counts. A tab may be stopped only at a break (which the account fallback's `read_tab_break` reads); a tab that
keeps answering is asked once to come to one (`should_ask_to_hold`).

Used by `hold_patrol.py` and `hold_continue.py`.
"""
from __future__ import annotations

from datetime import datetime
from typing import Iterable

from backend.account_fallback.fallback_settings import AT_PCT_MAX, WEEKDAYS
from backend.account_hold.hold_settings import HoldRule
from backend.sleep.sleep_judgement import TURN_OPEN
from backend.usage.limit_state import limit_state

# A percentage no usage reaches, so that `limit_state` counts only the window that has a line.
NO_LINE_PCT = AT_PCT_MAX + 1


def hold_line_pct(rule: HoldRule, now: float) -> int | None:
    """The line of the 7 days at time `now`: the one `rule` names for that day of the week (by the local time of this
    machine, so it changes at 0:00), None when it names none (= the day has no line)."""
    return rule.seven_day_at_pct.get(WEEKDAYS[datetime.fromtimestamp(now).weekday()])


def is_over_line(rows: Iterable[dict], rule: HoldRule | None, now: float) -> bool | None:
    """Whether the 7 days of the account of `rule` are at the line of today or more, or its 5 hours at `five_hour_at_pct`
    or more, and that window has not reset. False for a day without a line and no line of the 5 hours (or no rule), None
    when the log says nothing about the account."""
    seven, five = (hold_line_pct(rule, now), rule.five_hour_at_pct) if rule is not None else (None, None)
    if rule is None or (seven is None and five is None):
        return False
    state = limit_state(rows, rule.account, NO_LINE_PCT if five is None else five, now,
                        seven_day_line_pct=NO_LINE_PCT if seven is None else seven)
    return None if state is None else state.at_limit


def _window_over(rows: Iterable[dict], rule: HoldRule, now: float, *, five_line: int, seven_line: int) -> bool:
    state = limit_state(rows, rule.account, five_line, now, seven_day_line_pct=seven_line)
    return state is not None and state.at_limit


def reached_line_pct(rows: Iterable[dict], rule: HoldRule, now: float) -> int | None:
    """The line of the window of the account of `rule` that is at its line (the 7 days first), None when none is."""
    seven, five = hold_line_pct(rule, now), rule.five_hour_at_pct
    if seven is not None and _window_over(rows, rule, now, five_line=NO_LINE_PCT, seven_line=seven):
        return seven
    if five is not None and _window_over(rows, rule, now, five_line=five, seven_line=NO_LINE_PCT):
        return five
    return None


def should_ask_to_hold(*, blocked_by: tuple[str, ...], stopped_by_limit: bool, asked_at: float | None) -> bool:
    """Whether the tab is asked to come to a break: it is held because claude is answering (`turn_open` among
    `blocked_by`; a tab held only by commands, wake-ups or a call is not answering), no usage limit stopped it (that
    stop is its break) and it was not asked during this stay above the line (`asked_at` = None)."""
    return TURN_OPEN in blocked_by and not stopped_by_limit and asked_at is None
