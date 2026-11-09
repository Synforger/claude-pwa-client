"""Which `fallback` of the accounts is used and which is left out with a warning (`account_fallback/fallback_settings.py`)."""
from __future__ import annotations

import logging

import pytest

from backend.account_fallback.fallback_settings import FallbackRule, parse_rules, read_rules, warn_unusable
from backend.tests.limit_samples import use_accounts


def _accounts(**fallbacks) -> dict:
    accounts = {"personal": {"env": {}}, "work": {"env": {}}}
    for name, fallback in fallbacks.items():
        accounts.setdefault(name, {"env": {}})["fallback"] = fallback
    return accounts


def test_a_fallback_names_where_its_tabs_go_and_the_usage_they_go_at():
    rules, problems = parse_rules(_accounts(work={"to": "personal", "at_pct": 95}))
    assert rules == {"work": FallbackRule("work", "personal", 95)} and problems == ()


def test_without_a_fallback_nothing_is_set():
    assert parse_rules(_accounts()) == ({}, ())
    assert parse_rules(None) == ({}, ())


@pytest.mark.parametrize("fallback", [
    {"to": "nowhere", "at_pct": 95},                  # not an account of the configuration
    {"to": "work", "at_pct": 95},                     # the account itself
    {"to": "personal"},                               # no line: there is no default
    {"to": "personal", "at_pct": 0}, {"to": "personal", "at_pct": 101}, {"to": "personal", "at_pct": 95.5},
    {"to": "personal", "at_pct": "95"}, {"to": "personal", "at_pct": True},
    "personal", None,
])
def test_a_fallback_that_cannot_be_used_is_left_out_and_named(fallback):
    rules, problems = parse_rules(_accounts(work=fallback))
    assert rules == {} and len(problems) == 1 and problems[0].startswith("accounts.work.fallback is ignored")


def test_the_two_ends_of_the_line_are_allowed():
    assert parse_rules(_accounts(work={"to": "personal", "at_pct": 1}))[0]["work"].at_pct == 1
    assert parse_rules(_accounts(work={"to": "personal", "at_pct": 100}))[0]["work"].at_pct == 100


def test_the_account_it_moves_to_may_not_move_its_own_tabs_back_or_on():
    rules, problems = parse_rules(_accounts(work={"to": "personal", "at_pct": 95},
                                            personal={"to": "work", "at_pct": 95}))
    assert rules == {} and len(problems) == 2           # the reverse direction: both are left out
    chain = {"a": {"fallback": {"to": "b", "at_pct": 90}}, "b": {"fallback": {"to": "c", "at_pct": 90}}, "c": {}}
    rules, problems = parse_rules(chain)
    assert list(rules) == ["b"] and len(problems) == 1   # a chain: the first link is left out


def test_startup_names_each_unusable_fallback_in_one_line(monkeypatch, caplog):
    use_accounts(monkeypatch, _accounts(work={"to": "personal", "at_pct": 0}))
    with caplog.at_level(logging.WARNING):
        warn_unusable()
    assert [r.getMessage() for r in caplog.records if "account fallback" in r.getMessage()] == [
        "account fallback: accounts.work.fallback is ignored: `at_pct` is not a whole number from 1 to 100: 0"]
    assert read_rules() == {}


WEEK = {"mon": 70, "tue": 76, "wed": 82, "thu": 88, "fri": 94, "sat": 100, "sun": 70}


def test_a_table_of_lines_by_day_of_the_week_is_kept_with_the_rule():
    rules, problems = parse_rules(_accounts(work={"to": "personal", "at_pct": 95, "seven_day_at_pct": WEEK}))
    assert rules["work"] == FallbackRule("work", "personal", 95, WEEK) and problems == ()


def test_a_table_may_name_only_some_days():
    rules, problems = parse_rules(_accounts(work={"to": "personal", "at_pct": 95, "seven_day_at_pct": {"sat": 100}}))
    assert rules["work"].seven_day_at_pct == {"sat": 100} and problems == ()


def test_without_a_table_every_day_has_the_line_of_at_pct():
    rules, _ = parse_rules(_accounts(work={"to": "personal", "at_pct": 95}))
    assert rules["work"].seven_day_at_pct == {}


@pytest.mark.parametrize("table", [
    "mon", None, [70], 70,                           # not an object
    {"monday": 70}, {"Mon": 70}, {"": 70},           # not a name of a day
    {"mon": 0}, {"mon": 101}, {"mon": 70.5}, {"mon": "70"}, {"mon": True}, {"mon": None},   # not a line
    {"mon": 70, "sat": 101},                         # one bad entry spoils the table
])
def test_a_table_that_cannot_be_used_leaves_the_whole_fallback_out_and_names_why(table):
    rules, problems = parse_rules(_accounts(work={"to": "personal", "at_pct": 95, "seven_day_at_pct": table}))
    assert rules == {} and len(problems) == 1
    assert problems[0].startswith("accounts.work.fallback is ignored: `seven_day_at_pct")


def test_the_two_ends_of_a_daily_line_are_allowed():
    table = {"mon": 1, "sat": 100}
    rules, problems = parse_rules(_accounts(work={"to": "personal", "at_pct": 95, "seven_day_at_pct": table}))
    assert rules["work"].seven_day_at_pct == table and problems == ()


def test_startup_names_a_table_that_cannot_be_used(monkeypatch, caplog):
    use_accounts(monkeypatch, _accounts(work={"to": "personal", "at_pct": 95, "seven_day_at_pct": {"mon": 0}}))
    with caplog.at_level(logging.WARNING):
        warn_unusable()
    assert [r.getMessage() for r in caplog.records if "account fallback" in r.getMessage()] == [
        "account fallback: accounts.work.fallback is ignored: "
        "`seven_day_at_pct.mon` is not a whole number from 1 to 100: 0"]
