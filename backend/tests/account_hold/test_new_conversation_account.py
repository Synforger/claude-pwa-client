"""The account a tab's new conversation starts on (`account_hold/new_conversation_account.py`): the account it may run
on now, as a sleeping tab would wake on, with the marks of the conversation that ended dropped."""
from __future__ import annotations

import time

import pytest

import backend.account_hold.new_conversation_account as new_conversation
from backend._common.state import SleepMark
from backend.account_hold.hold_mail import clear_account_for
from backend.account_hold.hold_settings import read_rules
from backend.tests.account_hold.conftest import accounts, usage_row
from backend.tests.limit_samples import use_accounts

WORK_LINE = 90


@pytest.fixture
def work_tab(env, monkeypatch):
    """`env.other` is a tab of `work`, whose fallback is `personal` from 90 % of the 5 hours."""
    use_accounts(monkeypatch, accounts(work_fallback=WORK_LINE))
    monkeypatch.setattr(new_conversation, "read_all_rate_limits_tail", lambda: env.rows)
    monkeypatch.setattr(new_conversation, "save_sessions_meta", lambda: None)
    return env.other


def _usage(env, *, work: int, personal: int) -> None:
    env.rows = [usage_row("work", five=work, seven=10), usage_row("personal", five=10, seven=personal)]


def _choose(tab) -> str | None:
    return new_conversation.choose_account_for_new_conversation(tab.id)


def test_a_moved_tab_starts_its_new_conversation_back_on_its_own_account_once_that_is_clear(env, work_tab):
    work_tab.account_id, work_tab.fallback_from, work_tab.fallback_copy = "personal", "work", "/copy.jsonl"
    _usage(env, work=20, personal=10)
    assert _choose(work_tab) == "work"
    assert (work_tab.account_id, work_tab.fallback_from, work_tab.fallback_copy) == ("work", None, None)


def test_a_tab_whose_account_is_at_its_line_starts_its_new_conversation_on_the_fallback(env, work_tab):
    _usage(env, work=WORK_LINE + 2, personal=10)
    assert _choose(work_tab) == "personal"
    assert (work_tab.account_id, work_tab.fallback_from) == ("personal", "work")


def test_a_moved_tab_that_stays_on_the_fallback_forgets_the_record_of_the_conversation_that_ended(env, work_tab):
    # a later move back would otherwise delete that record, which holds the part of the conversation run there
    work_tab.account_id, work_tab.fallback_from, work_tab.fallback_copy = "personal", "work", "/copy.jsonl"
    _usage(env, work=WORK_LINE + 2, personal=10)
    assert _choose(work_tab) is None
    assert (work_tab.account_id, work_tab.fallback_from, work_tab.fallback_copy) == ("personal", "work", None)


def test_a_tab_no_account_is_clear_for_starts_where_it_is(env, work_tab):
    _usage(env, work=WORK_LINE + 2, personal=95)
    assert _choose(work_tab) is None
    assert (work_tab.account_id, work_tab.fallback_from) == ("work", None)


def test_a_tab_that_runs_where_it_may_stays(env, work_tab):
    _usage(env, work=20, personal=10)
    assert _choose(work_tab) is None and work_tab.account_id == "work"


def test_a_pinned_tab_on_its_own_account_stays(env, work_tab):
    work_tab.account_pinned = True
    _usage(env, work=WORK_LINE + 2, personal=10)
    assert _choose(work_tab) is None and work_tab.account_id == "work"


@pytest.mark.parametrize("work", [20, WORK_LINE + 2])
def test_a_pinned_tab_running_elsewhere_starts_where_it_would_wake(env, work_tab, work):
    work_tab.account_pinned = True
    work_tab.account_id, work_tab.fallback_from = "personal", "work"
    _usage(env, work=work, personal=10)
    wakes_on = clear_account_for(work_tab, env.rows, read_rules(), time.time(), for_messages=True)
    _choose(work_tab)
    assert work_tab.account_id == (wakes_on or "personal")


def test_a_tab_whose_account_has_no_fallback_stays(env, work_tab):
    _usage(env, work=20, personal=95)
    assert _choose(env.tab) is None and env.tab.account_id == "personal"


def test_the_marks_of_the_conversation_that_ended_are_dropped(env, work_tab):
    work_tab.owes_carry_on, work_tab.pause_asked_at, work_tab.hold_asked_at = True, 100.0, 200.0
    _usage(env, work=20, personal=10)
    _choose(work_tab)
    assert (work_tab.owes_carry_on, work_tab.pause_asked_at, work_tab.hold_asked_at) == (False, None, None)


@pytest.mark.parametrize("left", ["asleep", "held"])
def test_a_sleeping_or_stopped_tab_is_left_alone(env, work_tab, left):
    if left == "asleep":
        work_tab.sleep = SleepMark(claude_sid="c1", record="/r.jsonl", slept_at=1)
    else:
        work_tab.held_at = 100.0
    work_tab.account_id, work_tab.fallback_from, work_tab.owes_carry_on = "personal", "work", True
    _usage(env, work=20, personal=10)
    assert _choose(work_tab) is None
    assert (work_tab.account_id, work_tab.owes_carry_on) == ("personal", True)


def test_an_unknown_tab_is_left_alone(env, work_tab):
    assert new_conversation.choose_account_for_new_conversation("ses_gone") is None
