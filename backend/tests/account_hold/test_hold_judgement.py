"""Whether the account hold stops the tabs of an account (`hold_judgement.py`): the line of the day for the 7 days, the
line of the 5 hours, and the usage against them."""
from __future__ import annotations

import time
from datetime import datetime

import pytest

from backend.account_fallback.fallback_settings import FallbackRule
from backend.account_hold.hold_judgement import (
    hold_line_pct, is_over_line, reached_line_pct, resumes_on_home, should_ask_to_hold)
from backend.account_hold.hold_settings import HoldRule
from backend.sleep.sleep_judgement import PROCESSES_RUNNING, TURN_OPEN

MONDAY_NOON = datetime(2026, 11, 9, 12, 0).timestamp()
TUESDAY_NOON = datetime(2026, 11, 10, 12, 0).timestamp()
RULE = HoldRule("personal", {"mon": 70, "sat": 100})


def row(five=10, seven=10, now=MONDAY_NOON, account="personal", seven_resets=None) -> dict:
    return {"timestamp": now - 5, "account_id": account, "five_hour_pct": five, "five_hour_resets_at": now + 3600,
            "seven_day_pct": seven, "seven_day_resets_at": seven_resets if seven_resets is not None else now + 86400}


def test_the_line_is_the_one_of_the_day_of_the_week_and_a_day_without_one_has_none():
    assert hold_line_pct(RULE, MONDAY_NOON) == 70
    assert hold_line_pct(RULE, TUESDAY_NOON) is None


@pytest.mark.parametrize("seven, over", [(69, False), (70, True), (95, True)])
def test_the_7_days_are_over_the_line_of_the_day_at_the_line_or_more(seven, over):
    assert is_over_line([row(seven=seven)], RULE, MONDAY_NOON) is over


def test_the_5_hours_never_count_without_a_line_of_their_own():
    assert is_over_line([row(five=100, seven=10)], RULE, MONDAY_NOON) is False


FIVE_RULE = HoldRule("personal", {"mon": 70, "sat": 100}, five_hour_at_pct=95)


@pytest.mark.parametrize("five, over", [(94, False), (95, True), (100, True)])
def test_the_5_hours_are_over_their_line_at_the_line_or_more(five, over):
    assert is_over_line([row(five=five, seven=10)], FIVE_RULE, MONDAY_NOON) is over


def test_either_window_over_its_line_is_over_the_line():
    assert is_over_line([row(five=10, seven=70)], FIVE_RULE, MONDAY_NOON) is True
    assert is_over_line([row(five=95, seven=10)], FIVE_RULE, MONDAY_NOON) is True
    assert is_over_line([row(five=94, seven=69)], FIVE_RULE, MONDAY_NOON) is False


def test_the_5_hours_stop_on_a_day_whose_7_days_have_no_line():
    assert is_over_line([row(five=95, seven=100, now=TUESDAY_NOON)], FIVE_RULE, TUESDAY_NOON) is True
    assert is_over_line([row(five=94, seven=100, now=TUESDAY_NOON)], FIVE_RULE, TUESDAY_NOON) is False


def test_a_line_of_the_5_hours_alone_is_a_rule():
    only_five = HoldRule("personal", {}, five_hour_at_pct=95)
    assert is_over_line([row(five=95, seven=100)], only_five, MONDAY_NOON) is True
    assert is_over_line([row(five=94, seven=100)], only_five, MONDAY_NOON) is False


def test_a_5_hours_window_that_has_reset_is_not_over_its_line():
    usage = row(five=99, seven=10)
    usage["five_hour_resets_at"] = MONDAY_NOON - 60
    assert is_over_line([usage], FIVE_RULE, MONDAY_NOON) is False


def test_the_line_reached_is_the_one_of_the_window_that_is_at_it_and_the_7_days_come_first():
    assert reached_line_pct([row(five=10, seven=70)], FIVE_RULE, MONDAY_NOON) == 70
    assert reached_line_pct([row(five=95, seven=10)], FIVE_RULE, MONDAY_NOON) == 95
    assert reached_line_pct([row(five=95, seven=70)], FIVE_RULE, MONDAY_NOON) == 70
    assert reached_line_pct([row(five=10, seven=10)], FIVE_RULE, MONDAY_NOON) is None
    assert reached_line_pct([row(five=95, seven=100, now=TUESDAY_NOON)], FIVE_RULE, TUESDAY_NOON) == 95


def test_a_day_without_a_line_is_never_over_it():
    assert is_over_line([row(seven=100, now=TUESDAY_NOON)], RULE, TUESDAY_NOON) is False


def test_the_line_changes_at_midnight_with_the_same_usage():
    usage = row(seven=80)
    assert is_over_line([usage], RULE, datetime(2026, 11, 9, 23, 59).timestamp()) is True
    assert is_over_line([usage], RULE, datetime(2026, 11, 10, 0, 1).timestamp()) is False


def test_a_window_that_has_reset_is_not_over_the_line():
    assert is_over_line([row(seven=90, seven_resets=MONDAY_NOON - 60)], RULE, MONDAY_NOON) is False


def test_a_log_that_says_nothing_about_the_account_is_not_known():
    assert is_over_line([], RULE, MONDAY_NOON) is None
    assert is_over_line([row(account="work", seven=99)], RULE, MONDAY_NOON) is None


def test_an_account_without_a_rule_is_never_over_a_line():
    assert is_over_line([row(seven=100)], None, MONDAY_NOON) is False


@pytest.mark.parametrize("blocked_by, stopped, asked_at, asks", [
    ((TURN_OPEN,), False, None, True),
    ((TURN_OPEN, PROCESSES_RUNNING), False, None, True),
    ((PROCESSES_RUNNING,), False, None, False),        # held only by commands: not answering
    ((), False, None, False),                          # at a break: stopped, not asked
    ((TURN_OPEN,), True, None, False),                 # the limit's own stop is its break
    ((TURN_OPEN,), False, time.time(), False),         # asked during this stay above the line
])
def test_a_tab_is_asked_once_to_come_to_a_break_only_while_it_keeps_answering(blocked_by, stopped, asked_at, asks):
    assert should_ask_to_hold(blocked_by=blocked_by, stopped_by_limit=stopped, asked_at=asked_at) is asks


# --- a stopped tab goes back to the account it belongs to ---

WORK = FallbackRule("work", "personal", 95)


def _resumes(*, current="personal", rule=WORK, limited=False, near=False, target_over_line=True, pinned=False) -> bool:
    return resumes_on_home(current=current, home="work", rule=rule, limited=limited, near=near,
                           target_over_line=target_over_line, pinned=pinned)


@pytest.mark.parametrize("facts, expected", [
    ({}, True),                                                   # work is clear
    ({"limited": True, "near": True}, False),                     # work is at its line
    ({"limited": None, "near": None}, False),                     # nothing is known about work
    ({"rule": None}, False),                                      # work has no fallback any more
    ({"near": True, "target_over_line": False}, False),           # within the width, and personal is clear
    ({"near": True, "target_over_line": True}, True),             # within the width, but personal is at its line
    ({"pinned": True}, True),                                     # a pinned tab goes home as soon as work is clear
    ({"pinned": True, "limited": True, "near": True}, False),     # but not into a work that is at its line
    ({"current": "work"}, True),                                  # brought back already, the message was not taken
    ({"current": "work", "near": True}, False),
    ({"current": "work", "limited": True, "near": True}, False),
])
def test_a_stopped_tab_goes_back_and_carries_on_only_when_the_account_it_belongs_to_is_clear(facts, expected):
    assert _resumes(**facts) is expected
