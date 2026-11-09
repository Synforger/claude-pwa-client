"""Whether a tab is moved, brought back or left (`account_fallback/fallback_judgement.py`)."""
from __future__ import annotations

import time
from datetime import datetime

from backend.account_fallback.fallback_judgement import Move, decide, home_is_limited, seven_day_line_pct
from backend.account_fallback.fallback_settings import FallbackRule
from backend.tests.account_fallback.conftest import usage_row

RULE = FallbackRule("work", "personal", 95)
WEEK = {"mon": 70, "tue": 76, "wed": 82, "thu": 88, "fri": 94, "sat": 100, "sun": 70}
WEEKLY_RULE = FallbackRule("work", "personal", 95, WEEK)
# 2026-11-09 is a Monday and 2026-11-14 a Saturday; the times are of the local clock, as the judgement reads them.
MONDAY_NOON = datetime(2026, 11, 9, 12, 0).timestamp()
SATURDAY_NOON = datetime(2026, 11, 14, 12, 0).timestamp()


def _row_at(now: float, five: float, seven: float) -> dict:
    return usage_row(five=five, seven=seven, ts=now - 5, five_resets=now + 3600, seven_resets=now + 86400)


def test_the_usage_of_the_account_a_tab_belongs_to_is_judged_against_the_line_of_its_fallback():
    now = time.time()
    assert home_is_limited([usage_row(five=95)], RULE, now) is True
    assert home_is_limited([usage_row(five=10, seven=95)], RULE, now) is True      # either window
    assert home_is_limited([usage_row(five=94, seven=94)], RULE, now) is False
    assert home_is_limited([usage_row("personal", five=100)], RULE, now) is None   # nothing about this account
    assert home_is_limited([usage_row(five=99, five_resets=now - 1)], RULE, now) is False   # that window reset


def test_a_tab_on_its_own_account_moves_when_the_account_is_limited_and_the_tab_is_at_a_break():
    assert decide(current="work", home="work", rule=RULE, limited=True, at_break=True) is Move.MOVE
    assert decide(current="work", home="work", rule=RULE, limited=True, at_break=False) is Move.STAY
    assert decide(current="work", home="work", rule=RULE, limited=False, at_break=True) is Move.STAY
    assert decide(current="work", home="work", rule=RULE, limited=None, at_break=True) is Move.STAY


def test_an_account_without_a_fallback_never_moves_its_tabs():
    assert decide(current="personal", home="personal", rule=None, limited=True, at_break=True) is Move.STAY


def test_a_moved_tab_is_brought_back_when_the_account_is_not_limited_and_the_tab_is_at_a_break():
    assert decide(current="personal", home="work", rule=RULE, limited=False, at_break=True) is Move.RETURN
    assert decide(current="personal", home="work", rule=RULE, limited=False, at_break=False) is Move.STAY
    assert decide(current="personal", home="work", rule=RULE, limited=True, at_break=True) is Move.STAY
    assert decide(current="personal", home="work", rule=RULE, limited=None, at_break=True) is Move.STAY


def test_a_moved_tab_whose_fallback_is_gone_from_the_configuration_is_brought_back():
    assert decide(current="personal", home="work", rule=None, limited=None, at_break=True) is Move.RETURN


def test_a_pinned_tab_is_never_moved():
    assert decide(current="work", home="work", rule=RULE, limited=True, at_break=True, pinned=True) is Move.STAY


def test_a_pinned_tab_that_runs_elsewhere_comes_back_at_a_break_even_while_the_account_is_limited():
    assert decide(current="personal", home="work", rule=RULE, limited=True, at_break=True, pinned=True) is Move.RETURN
    assert decide(current="personal", home="work", rule=RULE, limited=True, at_break=False, pinned=True) is Move.STAY
    assert decide(current="personal", home="work", rule=RULE, limited=None, at_break=True, pinned=True) is Move.RETURN


def test_the_line_of_the_7_days_is_the_one_of_the_day_of_the_week():
    assert [seven_day_line_pct(WEEKLY_RULE, MONDAY_NOON + day * 86400) for day in range(7)] == [
        70, 76, 82, 88, 94, 100, 70]


def test_the_line_of_the_7_days_changes_at_midnight_of_the_local_clock():
    saturday = datetime(2026, 11, 14).timestamp()
    assert seven_day_line_pct(WEEKLY_RULE, saturday - 1) == 94      # Friday 23:59:59
    assert seven_day_line_pct(WEEKLY_RULE, saturday) == 100         # Saturday 0:00
    assert seven_day_line_pct(WEEKLY_RULE, saturday + 86400 - 1) == 100
    assert seven_day_line_pct(WEEKLY_RULE, saturday + 86400) == 70  # Sunday 0:00


def test_a_day_the_table_does_not_name_and_a_rule_without_a_table_use_at_pct():
    partial = FallbackRule("work", "personal", 95, {"sat": 100})
    assert seven_day_line_pct(partial, MONDAY_NOON) == 95 and seven_day_line_pct(partial, SATURDAY_NOON) == 100
    assert seven_day_line_pct(RULE, MONDAY_NOON) == 95 and seven_day_line_pct(RULE, SATURDAY_NOON) == 95


def test_the_same_usage_of_the_7_days_moves_the_tabs_on_monday_and_not_on_saturday():
    monday, saturday = _row_at(MONDAY_NOON, five=10, seven=80), _row_at(SATURDAY_NOON, five=10, seven=80)
    assert home_is_limited([monday], WEEKLY_RULE, MONDAY_NOON) is True         # 80 >= 70
    assert home_is_limited([saturday], WEEKLY_RULE, SATURDAY_NOON) is False    # 80 < 100
    assert home_is_limited([monday], RULE, MONDAY_NOON) is False               # without a table: at_pct 95


def test_the_usage_at_the_line_of_the_day_is_limited_and_one_below_is_not():
    assert home_is_limited([_row_at(MONDAY_NOON, 10, 70)], WEEKLY_RULE, MONDAY_NOON) is True
    assert home_is_limited([_row_at(MONDAY_NOON, 10, 69)], WEEKLY_RULE, MONDAY_NOON) is False
    assert home_is_limited([_row_at(SATURDAY_NOON, 10, 100)], WEEKLY_RULE, SATURDAY_NOON) is True
    assert home_is_limited([_row_at(SATURDAY_NOON, 10, 99)], WEEKLY_RULE, SATURDAY_NOON) is False


def test_the_5_hours_keep_the_line_of_at_pct_on_every_day():
    for now in (MONDAY_NOON, SATURDAY_NOON):
        assert home_is_limited([_row_at(now, five=94, seven=10)], WEEKLY_RULE, now) is False
        assert home_is_limited([_row_at(now, five=95, seven=10)], WEEKLY_RULE, now) is True


def test_a_moved_tab_returns_by_the_line_of_the_day_the_usage_is_read_on():
    row = _row_at(MONDAY_NOON, five=10, seven=80)                      # the same row, read on two days
    on_monday = home_is_limited([row], WEEKLY_RULE, MONDAY_NOON)
    on_saturday = home_is_limited([row], WEEKLY_RULE, SATURDAY_NOON)
    assert decide(current="personal", home="work", rule=WEEKLY_RULE, limited=on_monday, at_break=True) is Move.STAY
    assert decide(current="personal", home="work", rule=WEEKLY_RULE, limited=on_saturday, at_break=True) is Move.RETURN
