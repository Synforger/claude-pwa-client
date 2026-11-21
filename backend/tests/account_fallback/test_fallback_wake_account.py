"""The account a sleeping tab runs on once it is woken (`fallback_patrol.accounts_on_wake`), which the lists show. It is
the judgement `move_before_wake` acts on, and showing it moves nothing."""
from __future__ import annotations

import time

import pytest

import backend.account_fallback.fallback_patrol as patrol
from backend._common.state import SleepMark
from backend.tests.account_fallback.conftest import env, usage_row  # noqa: F401  (= the fixture of these tests)
from backend.tests.async_run import run


def _asleep(env) -> None:
    env.tab.sleep = SleepMark(claude_sid="OLD", record=str(env.src), slept_at=int(time.time()),
                              account_id=env.tab.account_id)


def _read(env):
    return lambda: env.rows


def test_a_sleeping_tab_whose_account_is_at_its_line_is_shown_on_the_account_it_will_wake_on(env):
    _asleep(env)
    env.rows = [usage_row(five=100)]
    assert patrol.accounts_on_wake(_read(env)) == {env.tab.id: "personal"}
    assert (env.tab.account_id, env.tab.fallback_from, env.events) == ("work", None, [])     # nothing was moved


def test_a_sleeping_tab_whose_account_is_clear_is_shown_where_it_slept(env):
    _asleep(env)
    env.rows = [usage_row(five=50)]
    assert patrol.accounts_on_wake(_read(env)) == {env.tab.id: "work"}


def test_a_sleeping_tab_that_was_moved_is_shown_on_its_own_account_once_that_is_clear(env):
    env.tab.account_id, env.tab.fallback_from = "personal", "work"
    _asleep(env)
    env.rows = [usage_row(five=50)]
    assert patrol.accounts_on_wake(_read(env)) == {env.tab.id: "work"}


def test_a_sleeping_tab_that_is_pinned_is_shown_where_it_slept(env):
    env.tab.account_pinned = True
    _asleep(env)
    env.rows = [usage_row(five=100)]
    assert patrol.accounts_on_wake(_read(env)) == {env.tab.id: "work"}


def test_a_tab_that_is_awake_is_not_in_the_answer_and_the_log_is_not_read_for_it(env):
    env.rows = [usage_row(five=100)]

    def must_not_read():
        raise AssertionError("no tab sleeps, so nothing needs the usage log")
    assert patrol.accounts_on_wake(must_not_read) == {}


def test_the_usage_log_is_read_once_for_all_the_sleeping_tabs(env):
    _asleep(env)
    other = env.tab.__class__(id="ses_other", agent_id=env.tab.agent_id, title="other", created_at=0,
                              account_id="work", sleep=env.tab.sleep)
    patrol.sessions_meta[other.id] = other
    env.rows = [usage_row(five=100)]
    reads: list[int] = []

    def read():
        reads.append(1)
        return env.rows
    assert patrol.accounts_on_wake(read) == {env.tab.id: "personal", "ses_other": "personal"}
    assert len(reads) == 1


@pytest.mark.parametrize("five", [100, 50])
def test_the_account_shown_is_the_account_the_tab_wakes_on(env, five):
    _asleep(env)
    env.rows = [usage_row(five=five)]
    shown = patrol.accounts_on_wake(_read(env))[env.tab.id]
    run(patrol.move_before_wake(env.tab.id))
    assert env.tab.account_id == shown


def test_a_sleeping_tab_moved_by_hand_to_an_account_at_its_line_is_shown_on_that_account(env):
    import backend.routes.sessions as sessions_mod  # noqa: PLC0415
    env.tab.account_id = "personal"
    run(sessions_mod.move_session_account(env.tab.id, {"account_id": "work"}))
    _asleep(env)
    env.rows = [usage_row(five=100)]
    assert patrol.accounts_on_wake(_read(env)) == {env.tab.id: "work"}


def test_a_sleeping_tab_the_fallback_moved_is_not_held_there_by_the_move(env):
    env.tab.account_id, env.tab.fallback_from = "personal", "work"
    _asleep(env)
    env.rows = [usage_row(five=100)]
    assert patrol.accounts_on_wake(_read(env)) == {env.tab.id: "personal"}
