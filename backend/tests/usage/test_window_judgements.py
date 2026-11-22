"""What the account fallback, the account hold and the limit resume make of an account that has both windows, only
one of them, or neither: one case for each shape of the account's usage. Run by pytest."""
from __future__ import annotations

from datetime import datetime

import pytest

from backend.account_fallback.fallback_judgement import home_is_limited, home_is_near
from backend.account_fallback.fallback_settings import FallbackRule
from backend.account_hold.hold_judgement import is_over_line, reached_line_pct
from backend.account_hold.hold_settings import HoldRule
from backend.limit_resume.resume_judgement import should_resume
from backend.sleep.record_facts import LimitStop
from backend.usage.limit_state import limit_state

MONDAY_NOON = datetime(2026, 11, 9, 12, 0).timestamp()
TUESDAY_NOON = datetime(2026, 11, 10, 12, 0).timestamp()
FIVE_LINE = 95
MONDAY_LINE = 70
AHEAD = 5
FALLBACK = FallbackRule("work", "personal", FIVE_LINE, {"mon": MONDAY_LINE}, ahead_pct=AHEAD)
HOLD = HoldRule("work", {"mon": MONDAY_LINE}, five_hour_at_pct=FIVE_LINE)


def account_rows(five: float | None, seven: float | None, *, now: float = MONDAY_NOON,
                 five_resets_in: float = 3600) -> list[dict]:
    return [{"timestamp": now - 5, "account_id": "work",
             "five_hour_pct": five, "five_hour_resets_at": None if five is None else now + five_resets_in,
             "seven_day_pct": seven, "seven_day_resets_at": None if seven is None else now + 86400}]


@pytest.mark.parametrize(("rows", "is_limited", "is_near", "is_held"), [
    pytest.param(account_rows(95, 10), True, True, True, id="both-five-at-its-line"),
    pytest.param(account_rows(10, 10), False, False, False, id="both-below"),
    pytest.param(account_rows(None, 10), False, False, False, id="week-alone-below"),
    pytest.param(account_rows(None, 66), False, True, False, id="week-alone-within-the-width"),
    pytest.param(account_rows(None, 70), True, True, True, id="week-alone-at-the-line-of-the-day"),
    pytest.param(account_rows(99, 10, five_resets_in=-60), False, False, False, id="five-has-reset-week-below"),
    pytest.param(account_rows(99, 70, five_resets_in=-60), True, True, True, id="five-has-reset-week-at-its-line"),
    pytest.param(account_rows(95, None), True, True, True, id="five-alone-at-its-line"),
    pytest.param(account_rows(10, None), False, False, False, id="five-alone-below"),
    pytest.param([], None, None, None, id="no-row"),
])
def test_the_lines_are_judged_by_the_windows_the_account_has(
        rows: list[dict], is_limited: bool | None, is_near: bool | None, is_held: bool | None) -> None:
    assert home_is_limited(rows, FALLBACK, MONDAY_NOON) is is_limited
    assert home_is_near(rows, FALLBACK, MONDAY_NOON) is is_near
    assert is_over_line(rows, HOLD, MONDAY_NOON) is is_held


def test_a_blank_day_of_the_week_alone_uses_the_fallbacks_line_and_never_holds() -> None:
    rows = account_rows(None, FIVE_LINE, now=TUESDAY_NOON)
    assert home_is_limited(rows, FALLBACK, TUESDAY_NOON) is True
    assert is_over_line(rows, HOLD, TUESDAY_NOON) is False


def test_the_line_reached_by_the_week_alone_is_the_line_of_the_day() -> None:
    assert reached_line_pct(account_rows(None, 70), HOLD, MONDAY_NOON) == MONDAY_LINE


@pytest.mark.parametrize(("rows", "was_seen", "expected"), [
    pytest.param(account_rows(10, 10), True, True, id="both-came-down"),
    pytest.param(account_rows(None, 10), True, True, id="five-went-away-week-below"),
    pytest.param(account_rows(None, 10), False, False, id="week-below-never-seen-at-the-line"),
    pytest.param(account_rows(None, 95), True, False, id="week-alone-at-the-line"),
    pytest.param(account_rows(99, 10, five_resets_in=-60), False, True, id="five-reset-after-the-stop"),
    pytest.param(account_rows(10, None), True, True, id="five-alone-came-down"),
    pytest.param([], True, False, id="no-row"),
])
def test_a_limit_stop_is_resumed_by_the_windows_the_account_has(
        rows: list[dict], was_seen: bool, expected: bool) -> None:
    stop = LimitStop("stop", at=MONDAY_NOON - 600)
    state = limit_state(rows, "work", FIVE_LINE, MONDAY_NOON)
    assert should_resume(stop=stop, resumed=None, state=state, seen_at_limit=was_seen) is expected


def test_a_week_that_reset_after_the_stop_resumes_it() -> None:
    rows = account_rows(None, 99)
    after_reset = MONDAY_NOON + 86400 + 60
    state = limit_state(rows, "work", FIVE_LINE, after_reset)
    stop = LimitStop("stop", at=MONDAY_NOON)
    assert should_resume(stop=stop, resumed=None, state=state, seen_at_limit=False) is True
