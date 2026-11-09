"""The account hold settings (`hold_settings.py`): what is read from `accounts.<account>.hold`, and what is left out."""
from __future__ import annotations

import logging

import pytest

from backend.account_hold import hold_settings
from backend.account_hold.hold_settings import HoldRule, parse_rules
from backend.tests.limit_samples import use_accounts

PERSONAL = {"display_name": "Personal", "env": {}}
WORK = {"display_name": "Work", "env": {"CLAUDE_CONFIG_DIR": "/w"}}


def test_a_table_of_days_is_a_rule():
    rules, problems = parse_rules({"personal": {**PERSONAL, "hold": {"seven_day_at_pct": {"mon": 70, "sat": 100}}},
                                   "work": WORK})
    assert rules == {"personal": HoldRule("personal", {"mon": 70, "sat": 100})} and problems == ()


def test_an_empty_table_is_a_rule_that_stops_nothing():
    rules, problems = parse_rules({"personal": {**PERSONAL, "hold": {"seven_day_at_pct": {}}}})
    assert rules == {"personal": HoldRule("personal", {})} and problems == ()


@pytest.mark.parametrize("hold, reason", [
    ("mon", "it is not an object"),
    ({}, "`seven_day_at_pct` is missing"),
    ({"seven_day_at_pct": 70}, "`seven_day_at_pct` is not an object"),
    ({"seven_day_at_pct": {"monday": 70}}, "which is not one of mon"),
    ({"seven_day_at_pct": {"mon": 0}}, "`seven_day_at_pct.mon` is not a whole number from 1 to 100"),
    ({"seven_day_at_pct": {"mon": 101}}, "`seven_day_at_pct.mon` is not a whole number"),
    ({"seven_day_at_pct": {"mon": 70.5}}, "`seven_day_at_pct.mon` is not a whole number"),
    ({"seven_day_at_pct": {"mon": True}}, "`seven_day_at_pct.mon` is not a whole number"),
])
def test_a_hold_of_the_wrong_shape_is_left_out_with_the_reason(hold, reason):
    rules, problems = parse_rules({"personal": {**PERSONAL, "hold": hold}})
    assert rules == {}
    [problem] = problems
    assert problem.startswith("accounts.personal.hold is ignored: ") and reason in problem


def test_an_account_with_a_fallback_cannot_have_a_hold_and_the_fallback_stays():
    from backend.account_fallback import fallback_settings
    accounts = {"personal": PERSONAL,
                "work": {**WORK, "fallback": {"to": "personal", "at_pct": 95},
                         "hold": {"seven_day_at_pct": {"mon": 70}}}}
    rules, problems = parse_rules(accounts)
    assert rules == {} and "has a `fallback`" in problems[0]
    assert set(fallback_settings.parse_rules(accounts)[0]) == {"work"}


def test_one_bad_hold_does_not_take_the_others_with_it():
    rules, problems = parse_rules({"personal": {**PERSONAL, "hold": {"seven_day_at_pct": {"mon": 70}}},
                                   "work": {**WORK, "hold": 5}})
    assert set(rules) == {"personal"} and len(problems) == 1


def test_accounts_that_are_not_an_object_have_no_rules():
    assert parse_rules(None) == ({}, ()) and parse_rules(["personal"]) == ({}, ())


def test_the_warning_at_startup_names_each_hold_that_is_left_out(monkeypatch, caplog):
    use_accounts(monkeypatch, {"personal": {**PERSONAL, "hold": 3}})
    caplog.set_level(logging.WARNING, logger=hold_settings.logger.name)
    hold_settings.warn_unusable()
    assert "account hold: accounts.personal.hold is ignored: it is not an object" in caplog.text
