"""Whether the account hold stops the tabs of an account (`hold_judgement.py`): the line of the day, and the usage of
the 7 days against it."""
from __future__ import annotations

import time
from datetime import datetime

import pytest

from backend.account_hold.hold_judgement import hold_line_pct, is_over_line, should_ask_to_hold
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


def test_the_5_hours_never_count():
    assert is_over_line([row(five=100, seven=10)], RULE, MONDAY_NOON) is False


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
