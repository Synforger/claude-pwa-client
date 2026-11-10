"""Whether the account hold stops the tabs of an account, whether a tab is asked to come to a break first, and whether a
stopped tab goes back to the account it belongs to and carries on. Pure: it takes the facts and answers, and reads no
file, no log and no state.

The usage of an account is judged by `usage.limit_state` against the line the rule names for the day of the week for
its 7 days (`hold_line_pct`) and against its `five_hour_at_pct` for its 5 hours; a window the rule names no line for
never counts. A tab may be stopped only at a break (which the account fallback's `read_tab_break` reads); a tab that
keeps answering is asked once to come to one (`should_ask_to_hold`). A tab stopped on the account the fallback moved it
to goes back to the account it belongs to, and carries on, once that account is clear of its line
(`resumes_on_home`, which asks the fallback's `decide` the same question as the return of a cold tab).

Used by `hold_patrol.py`, `hold_resume.py` and `hold_continue.py`.
"""
from __future__ import annotations

from datetime import datetime
from typing import Iterable

from backend.account_fallback.fallback_judgement import Move, decide
from backend.account_fallback.fallback_settings import AT_PCT_MAX, WEEKDAYS, FallbackRule
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


def resumes_on_home(*, current: str, home: str, rule: FallbackRule | None, limited: bool | None, near: bool | None,
                    target_over_line: bool | None, pinned: bool) -> bool:
    """Whether a stopped tab that runs on `current` and belongs to `home` goes back to `home` and carries on: `rule` is
    the fallback of `home`, `limited` whether its usage is at the rule's line and `near` whether it is within the
    rule's `ahead_pct` of it, `target_over_line` whether `current` is at its own hold line.

    Never while `home` is at its line, or not known to be clear of it (`limited` is not False), or has no fallback: the
    stop was for both accounts being at their lines, and one of them still is. When `home` is clear, a tab that runs
    elsewhere goes back on the fallback's own terms (`decide` with a cold cache and at a break, which a stopped tab is by
    definition); a tab that runs on `home` already (= it was brought back but did not take the message) carries on once
    `home` is not within `ahead_pct` of its line."""
    if rule is None or limited is not False:
        return False
    if current == home:
        return near is False
    return decide(current=current, home=home, rule=rule, limited=limited, at_break=True, pinned=pinned, near=near,
                  cold=True, target_over_line=target_over_line) is Move.RETURN
