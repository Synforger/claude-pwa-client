"""A tab the account hold stopped on the account the fallback moved it to is brought back to the account it belongs to
and continued, once that account is clear of its line (`hold_resume.py`). The usage log, the move back, the sleep and
the message sent are the fixture's: `work` falls back to `personal`, and `personal` holds its tabs at 70 %."""
from __future__ import annotations

import logging

import pytest

from backend._common.state import SleepMark
from backend.account_hold import hold_resume
from backend.account_hold import hold_patrol as patrol
from backend.account_hold.hold_envelope import CONTINUE
from backend.accounts.tab_claim import claimed
from backend.jsonl.jsonl_predicates import CLIENT_NOTICE_OPENING
from backend.tests.account_hold.conftest import accounts, usage_row
from backend.tests.async_run import run
from backend.tests.limit_samples import use_accounts

WORK_LINE_PCT = 95


@pytest.fixture
def held(env, monkeypatch):
    """`env.tab` was moved from `work` to `personal` and stopped there, with `personal` over its hold line."""
    use_accounts(monkeypatch, accounts(work_fallback=WORK_LINE_PCT))
    env.tab.fallback_from = "work"
    env.tab.held_at = 100.0
    env.tab.sleep = SleepMark(claude_sid="c1", record="/r.jsonl", slept_at=1)
    return env


def _nothing_happened(env) -> bool:
    return (env.moved == [] and env.sent == [] and env.tab.held_at == 100.0 and env.tab.account_id == "personal"
            and env.tab.fallback_from == "work")


# --- work is clear of its line ---

def test_work_clear_of_its_line_takes_the_stopped_tab_back_and_continues_it(held, caplog):
    held.rows = [usage_row("work", seven=10), usage_row(seven=90)]
    caplog.set_level(logging.INFO, logger=hold_resume.logger.name)
    assert run(patrol.tick()) == []
    assert held.moved == [held.tab.id]
    assert (held.tab.account_id, held.tab.fallback_from, held.tab.held_at) == ("work", None, None)
    [(session_id, text)] = held.sent
    assert session_id == held.tab.id and text.splitlines()[0] == CLIENT_NOTICE_OPENING
    assert f'<account-hold phase="{CONTINUE}" account="work">' in text
    assert f"account hold: resumed on work session={held.tab.id} from=personal" in caplog.text


def test_the_5_hours_of_work_are_judged_too(held):
    held.rows = [usage_row("work", five=95, seven=10), usage_row(seven=90)]
    run(patrol.tick())
    assert _nothing_happened(held)
    held.rows = [usage_row("work", five=94, seven=10), usage_row(seven=90)]
    run(patrol.tick())
    assert held.tab.account_id == "work" and held.tab.held_at is None


def test_a_work_window_that_has_reset_no_longer_counts(held):
    held.rows = [usage_row("work", seven=99, seven_resets=1.0), usage_row(seven=90)]
    run(patrol.tick())
    assert held.tab.account_id == "work" and held.tab.held_at is None and len(held.sent) == 1


# --- work is not clear ---

def test_work_at_its_line_leaves_the_tab_stopped(held):
    held.rows = [usage_row("work", seven=96), usage_row(seven=90)]
    run(patrol.tick())
    assert _nothing_happened(held)


def test_work_whose_usage_is_not_known_leaves_the_tab_stopped(held):
    held.rows = [usage_row(seven=90)]
    run(patrol.tick())
    assert _nothing_happened(held)


def test_work_within_the_width_ahead_of_its_line_leaves_the_tab_stopped_while_personal_is_clear(held, monkeypatch):
    config = accounts(work_fallback=WORK_LINE_PCT)
    config["work"]["fallback"]["ahead_pct"] = 5
    use_accounts(monkeypatch, config)
    held.rows = [usage_row("work", seven=91), usage_row(seven=10)]
    run(patrol.tick())
    assert _nothing_happened(held)


def test_work_within_the_width_ahead_of_its_line_takes_the_tab_back_while_personal_is_at_its_line(held, monkeypatch):
    config = accounts(work_fallback=WORK_LINE_PCT)
    config["work"]["fallback"]["ahead_pct"] = 5
    use_accounts(monkeypatch, config)
    held.rows = [usage_row("work", seven=91), usage_row(seven=90)]
    run(patrol.tick())
    assert held.tab.account_id == "work" and held.tab.held_at is None


# --- only personal is clear ---

def test_personal_clear_while_work_is_at_its_line_continues_the_tab_where_it_is(held, caplog):
    held.rows = [usage_row("work", seven=96), usage_row(seven=10)]
    caplog.set_level(logging.INFO, logger=hold_resume.logger.name)
    run(patrol.tick())
    assert held.moved == [] and (held.tab.account_id, held.tab.held_at) == ("personal", None)
    [(session_id, text)] = held.sent
    assert session_id == held.tab.id and f'<account-hold phase="{CONTINUE}" account="personal">' in text
    assert f"account hold: resumed on personal session={held.tab.id} from=personal" in caplog.text


def test_personal_whose_usage_is_not_known_leaves_the_tab_stopped_for_the_operator(held):
    from backend.account_hold.hold_continue import continue_account
    held.rows = [usage_row("work", seven=96)]
    run(patrol.tick())
    assert _nothing_happened(held)
    assert run(continue_account("personal")).continued == (held.tab.id,) and held.tab.held_at is None


# --- pinned tabs ---

def test_a_pinned_tab_that_was_never_stopped_is_left_alone_when_work_is_clear(env, monkeypatch):
    use_accounts(monkeypatch, accounts(work_fallback=WORK_LINE_PCT))
    env.tab.fallback_from = "work"
    env.tab.account_pinned = True
    env.rows = [usage_row("work", seven=10), usage_row(seven=90)]
    run(patrol.tick())
    assert env.moved == [] and env.sent == [] and env.slept == [] and env.tab.account_id == "personal"


def test_a_stopped_tab_that_was_pinned_afterwards_continues_when_work_is_clear_and_not_before(held):
    held.tab.account_pinned = True
    held.rows = [usage_row("work", seven=96), usage_row(seven=90)]
    run(patrol.tick())
    assert _nothing_happened(held)
    held.rows = [usage_row("work", seven=10), usage_row(seven=90)]
    run(patrol.tick())
    assert held.tab.account_id == "work" and held.tab.held_at is None
    assert [session_id for session_id, _text in held.sent] == [held.tab.id, held.other.id]   # work's own tab too


# --- tabs that are not this one's ---

def test_a_tab_of_personal_itself_is_not_continued_when_work_is_clear(held):
    own = held.other
    own.account_id, own.held_at = "personal", 100.0
    own.sleep = SleepMark(claude_sid="c2", record="/r2.jsonl", slept_at=1)
    held.tab.held_at = None
    held.rows = [usage_row("work", seven=10), usage_row(seven=90)]
    run(patrol.tick())
    assert own.held_at == 100.0 and held.moved == [] and held.sent == []


def test_nothing_is_resumed_when_work_has_no_fallback(env):
    env.tab.fallback_from, env.tab.held_at = "work", 100.0
    env.tab.sleep = SleepMark(claude_sid="c1", record="/r.jsonl", slept_at=1)
    env.rows = [usage_row("work", seven=10), usage_row(seven=90)]
    run(patrol.tick())
    assert env.moved == [] and env.sent == [] and env.tab.held_at == 100.0


# --- when a step does not work ---

def test_a_tab_the_move_back_did_not_reach_is_not_continued_and_the_next_look_tries_again(held):
    held.rows = [usage_row("work", seven=10), usage_row(seven=90)]
    held.move_works = False
    run(patrol.tick())
    assert held.moved == [held.tab.id] and held.sent == [] and held.tab.held_at == 100.0
    assert held.tab.account_id == "personal"
    held.move_works = True
    run(patrol.tick())
    assert held.tab.account_id == "work" and held.tab.held_at is None and len(held.sent) == 1


def test_a_tab_that_is_being_worked_on_by_another_feature_is_left_for_the_next_look(held):
    held.rows = [usage_row("work", seven=10), usage_row(seven=90)]
    with claimed(held.tab.id):
        run(patrol.tick())
    assert held.sent == [] and held.tab.held_at == 100.0 and held.tab.account_id == "personal"
    run(patrol.tick())
    assert held.tab.account_id == "work" and held.tab.held_at is None


def test_a_tab_back_on_work_that_did_not_take_the_message_is_sent_it_again_without_another_move(held):
    held.rows = [usage_row("work", seven=10), usage_row(seven=90)]
    held.deliver = False
    run(patrol.tick())
    assert held.tab.account_id == "work" and held.tab.held_at == 100.0 and len(held.sent) == 1
    held.deliver = True
    run(patrol.tick())
    assert held.moved == [held.tab.id] and len(held.sent) == 2 and held.tab.held_at is None


def test_a_continued_tab_is_not_continued_again(held):
    held.rows = [usage_row("work", seven=10), usage_row(seven=90)]
    run(patrol.tick())
    run(patrol.tick())
    assert len(held.sent) == 1 and held.moved == [held.tab.id]
