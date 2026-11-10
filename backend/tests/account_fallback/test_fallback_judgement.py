"""Whether a tab is moved, brought back or left (`account_fallback/fallback_judgement.py`)."""
from __future__ import annotations

import time
from datetime import datetime

import pytest

from backend.account_fallback.fallback_judgement import (
    PROMPT_CACHE_LIFETIME_MIN, QUIET, Move, cold_reasons, decide, home_is_limited, home_is_near,
    returns_over_target_line, seven_day_line_pct, urgent_move)
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


# --- ahead of the line ---

AHEAD_RULE = FallbackRule("work", "personal", 95, ahead_pct=5)
AHEAD_WEEKLY_RULE = FallbackRule("work", "personal", 95, WEEK, ahead_pct=5)


def test_the_usage_is_near_the_line_from_the_width_ahead_of_it_and_not_before():
    now = time.time()
    assert home_is_near([usage_row(five=89)], AHEAD_RULE, now) is False
    assert home_is_near([usage_row(five=90)], AHEAD_RULE, now) is True
    assert home_is_near([usage_row(five=10, seven=90)], AHEAD_RULE, now) is True      # either window
    assert home_is_near([usage_row("personal", five=100)], AHEAD_RULE, now) is None    # nothing about this account
    assert home_is_near([usage_row(five=99, five_resets=now - 1)], AHEAD_RULE, now) is False   # that window reset


def test_the_usage_is_near_the_line_of_the_day_by_the_width_ahead_of_that_line():
    assert home_is_near([_row_at(MONDAY_NOON, 10, 65)], AHEAD_WEEKLY_RULE, MONDAY_NOON) is True      # 70 - 5
    assert home_is_near([_row_at(MONDAY_NOON, 10, 64)], AHEAD_WEEKLY_RULE, MONDAY_NOON) is False
    assert home_is_near([_row_at(SATURDAY_NOON, 10, 95)], AHEAD_WEEKLY_RULE, SATURDAY_NOON) is True   # 100 - 5
    assert home_is_near([_row_at(SATURDAY_NOON, 10, 94)], AHEAD_WEEKLY_RULE, SATURDAY_NOON) is False


def test_without_a_width_the_usage_is_near_exactly_when_it_is_limited():
    now = time.time()
    for five in (50, 94, 95, 100):
        row = [usage_row(five=five)]
        assert home_is_near(row, RULE, now) is home_is_limited(row, RULE, now)


def test_the_line_ahead_never_falls_below_the_lowest_line_that_can_be_set():
    low = FallbackRule("work", "personal", 3, ahead_pct=50)
    now = time.time()
    assert home_is_near([usage_row(five=0, seven=0)], low, now) is False
    assert home_is_near([usage_row(five=1, seven=0)], low, now) is True


def test_being_limited_is_being_near():
    now = time.time()
    for five in range(0, 101, 5):
        row = [usage_row(five=five)]
        assert home_is_limited(row, AHEAD_RULE, now) is not True or home_is_near(row, AHEAD_RULE, now) is True


# --- a cold cache ---

def test_the_cache_lifetime_is_an_hour():
    assert PROMPT_CACHE_LIFETIME_MIN == 60


@pytest.mark.parametrize("quiet, reasons", [
    (PROMPT_CACHE_LIFETIME_MIN, (QUIET,)),
    (PROMPT_CACHE_LIFETIME_MIN - 1, ()),
    (None, ()),                                           # nothing was read: not cold
])
def test_the_cache_is_cold_after_an_hour_of_quiet_only(quiet, reasons):
    # a tab at the rollover's line is not cold: the rollover starts its next conversation on the right account
    assert cold_reasons(quiet_minutes=quiet) == reasons


def test_a_tab_on_its_own_account_moves_ahead_of_the_line_only_when_its_cache_is_cold():
    ahead = dict(current="work", home="work", rule=AHEAD_RULE, limited=False, near=True, at_break=True)
    assert decide(**ahead, cold=True) is Move.MOVE
    assert decide(**ahead, cold=False) is Move.STAY
    assert decide(**{**ahead, "near": False}, cold=True) is Move.STAY
    assert decide(**{**ahead, "near": None}, cold=True) is Move.STAY
    assert decide(**{**ahead, "at_break": False}, cold=True) is Move.STAY
    assert decide(**ahead, cold=True, pinned=True) is Move.STAY


def test_a_tab_at_the_line_moves_whatever_its_cache_is():
    line = dict(current="work", home="work", rule=AHEAD_RULE, limited=True, near=True, at_break=True)
    assert decide(**line, cold=False) is Move.MOVE and decide(**line, cold=True) is Move.MOVE


def test_a_tab_is_not_moved_ahead_of_the_line_to_an_account_that_is_at_its_own_line():
    ahead = dict(current="work", home="work", rule=AHEAD_RULE, limited=False, near=True, at_break=True, cold=True)
    assert decide(**ahead, target_over_line=True) is Move.STAY
    assert decide(**ahead, target_over_line=False) is Move.MOVE and decide(**ahead, target_over_line=None) is Move.MOVE


def test_a_tab_at_the_line_is_not_moved_to_an_account_at_its_own_line_either():
    line = dict(current="work", home="work", rule=AHEAD_RULE, limited=True, near=True, at_break=True)
    assert decide(**line, cold=False, target_over_line=True) is Move.STAY    # both at their lines: the hold stops it
    assert decide(**line, cold=True, target_over_line=True) is Move.STAY
    assert decide(**line, cold=False, target_over_line=None) is Move.MOVE    # not known: it moves, as before
    assert urgent_move(current="work", home="work", rule=AHEAD_RULE, limited=True, target_over_line=True,
                       pinned=False) is Move.STAY                           # so it is not asked to pause either


def test_a_width_of_zero_moves_nothing_ahead():
    now = time.time()
    row = [usage_row(five=94)]
    near, limited = home_is_near(row, RULE, now), home_is_limited(row, RULE, now)
    assert decide(current="work", home="work", rule=RULE, limited=limited, near=near, at_break=True, cold=True) is Move.STAY


# --- coming back ---

def _away(**over):
    return {**dict(current="personal", home="work", rule=AHEAD_RULE, limited=False, near=False, at_break=True,
                   cold=True), **over}


def test_a_moved_tab_comes_back_when_the_account_is_clear_and_its_cache_is_cold_and_not_before():
    assert decide(**_away()) is Move.RETURN
    assert decide(**_away(cold=False)) is Move.STAY                       # a working tab is not brought back at once
    assert decide(**_away(at_break=False)) is Move.STAY


def test_a_moved_tab_stays_while_the_account_is_below_its_line_but_within_the_width_ahead_of_it():
    assert decide(**_away(limited=False, near=True)) is Move.STAY
    assert decide(**_away(limited=True, near=True)) is Move.STAY
    assert decide(**_away(limited=None, near=None)) is Move.STAY


def test_a_pinned_tab_and_a_tab_whose_fallback_is_gone_come_back_without_waiting_for_the_cache():
    assert decide(**_away(cold=False, pinned=True, limited=True, near=True)) is Move.RETURN
    assert decide(**_away(cold=False, rule=None, limited=None, near=None)) is Move.RETURN


def test_a_moved_tab_comes_back_at_once_when_the_account_it_runs_on_is_at_its_line_and_its_own_is_not():
    over = _away(cold=False, near=True, target_over_line=True)
    assert decide(**over) is Move.RETURN
    assert decide(**{**over, "at_break": False}) is Move.STAY
    assert decide(**{**over, "limited": True}) is Move.STAY                # both are at their lines: it stays, and stops
    assert decide(**{**over, "limited": None}) is Move.STAY                # not known: it stays
    assert decide(**{**over, "target_over_line": False}) is Move.STAY
    assert decide(**{**over, "target_over_line": None}) is Move.STAY


def test_the_return_over_the_line_of_the_account_it_runs_on_is_that_and_nothing_else():
    ok = dict(current="personal", home="work", rule=AHEAD_RULE, limited=False, target_over_line=True)
    assert returns_over_target_line(**ok) is True
    assert returns_over_target_line(**{**ok, "current": "work"}) is False        # on its own account
    assert returns_over_target_line(**{**ok, "rule": None}) is False
    assert returns_over_target_line(**{**ok, "limited": True}) is False
    assert returns_over_target_line(**{**ok, "limited": None}) is False
    assert returns_over_target_line(**{**ok, "target_over_line": False}) is False


def test_the_move_that_cannot_wait_for_the_cache_is_the_one_off_an_account_at_its_line_or_off_one_that_reached_its_own():
    own = dict(home="work", rule=AHEAD_RULE, pinned=False)
    assert urgent_move(current="work", limited=True, target_over_line=None, **own) is Move.MOVE
    assert urgent_move(current="work", limited=False, target_over_line=None, **own) is Move.STAY   # only near: it waits
    assert urgent_move(current="personal", limited=False, target_over_line=True, **own) is Move.RETURN
    assert urgent_move(current="personal", limited=False, target_over_line=False, **own) is Move.STAY
    assert urgent_move(current="personal", limited=True, target_over_line=True, **own) is Move.STAY


def test_a_pinned_tab_and_a_tab_without_a_fallback_have_no_urgent_move():
    assert urgent_move(current="personal", home="work", rule=AHEAD_RULE, limited=False, target_over_line=True,
                       pinned=True) is Move.STAY
    assert urgent_move(current="personal", home="work", rule=None, limited=None, target_over_line=True,
                       pinned=False) is Move.STAY
