"""Whether a tab is moved, brought back or left (`account_fallback/fallback_judgement.py`)."""
from __future__ import annotations

import time

from backend.account_fallback.fallback_judgement import Move, decide, home_is_limited
from backend.account_fallback.fallback_settings import FallbackRule
from backend.tests.account_fallback.conftest import usage_row

RULE = FallbackRule("work", "personal", 95)


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
