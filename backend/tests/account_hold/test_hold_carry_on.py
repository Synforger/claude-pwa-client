"""The message to carry on goes only to a tab the client owes it (`owes_carry_on`): one it asked to come to a break, or
one a usage limit stopped. A tab stopped with nothing left to do is released without a word, one request is sent per
tab, a request that is no longer needed is followed by the message once the tab is at a break, and only a tab that may
run is woken (`hold_patrol.py`, `hold_resume.py`, `hold_mail.py`). `personal` holds its tabs at 70 % of the 7 days,
`work` falls back to `personal` at 95 %."""
from __future__ import annotations

import time

import pytest

from backend._common.state import SleepMark, sessions_meta
from backend.account_fallback.fallback_sensors import TabBreak
from backend.account_hold import hold_mail, hold_resume
from backend.account_hold import hold_patrol as patrol
from backend.account_hold.hold_envelope import CONTINUE, STOP
from backend.account_hold.hold_settings import read_rules
from backend.sleep.record_facts import LimitStop
from backend.sleep.sleep_judgement import PROCESSES_RUNNING, TURN_OPEN
from backend.tests.account_hold.conftest import accounts, usage_row
from backend.tests.async_run import run
from backend.tests.limit_samples import use_accounts

BOTH_AT_LINES = [usage_row("work", seven=96), usage_row(seven=90)]
PERSONAL_CLEAR = [usage_row("work", seven=96), usage_row(seven=10)]


@pytest.fixture
def owed(env, monkeypatch):
    """`env.other` runs on `work`, which falls back to `personal`; what is read about a tab is the fixture's for the
    carry-on look too; moving a tab is recorded in `env.moved` and does nothing."""
    use_accounts(monkeypatch, accounts(work_fallback=95))
    monkeypatch.setattr(hold_mail, "read_all_rate_limits_tail", lambda: env.rows)
    monkeypatch.setattr(hold_resume, "read_tab_break", lambda _sid: TabBreak(env.stop, env.blocked_by))

    async def _move(session_id):
        env.moved.append(session_id)
        meta = sessions_meta[session_id]
        meta.account_id, meta.fallback_from = "personal", meta.account_id

    monkeypatch.setattr(hold_resume, "move_before_wake", _move)
    return env


def _stop(meta, *, owes: bool) -> None:
    meta.held_at = 100.0
    meta.owes_carry_on = owes
    meta.sleep = SleepMark(claude_sid="c1", record="/r.jsonl", slept_at=1)


def _texts_to(env, session_id) -> list[str]:
    return [text for sid, text in env.sent if sid == session_id]


# --- stopping marks what is owed ---

def test_a_tab_stopped_at_a_break_owes_nothing_and_one_asked_to_stop_owes_the_message(owed):
    owed.rows = BOTH_AT_LINES
    run(patrol.tick())
    assert owed.other.held_at is not None and owed.other.owes_carry_on is False
    owed.tab.sleep, owed.tab.held_at = None, None
    owed.other.sleep, owed.other.held_at = None, None
    owed.blocked_by = (TURN_OPEN,)
    run(patrol.tick())
    assert owed.other.owes_carry_on is True and owed.other.hold_asked_at is not None
    owed.blocked_by = ()
    run(patrol.tick())
    assert owed.other.held_at is not None and owed.other.owes_carry_on is True      # the stop keeps what is owed


def test_a_tab_a_usage_limit_stopped_owes_the_message(owed):
    owed.rows = BOTH_AT_LINES
    owed.stop = LimitStop(uuid="u1", at=1.0)
    run(patrol.tick())
    assert owed.other.held_at is not None and owed.other.owes_carry_on is True


def test_a_tab_that_is_owed_is_not_asked_a_second_time(owed):
    owed.rows = BOTH_AT_LINES
    owed.other.owes_carry_on = True                                   # the fallback asked it to pause already
    owed.blocked_by = (TURN_OPEN,)
    run(patrol.tick())
    assert not any(f'phase="{STOP}"' in text for text in _texts_to(owed, owed.other.id))


# --- carrying a stopped tab on ---

def test_a_tab_stopped_with_nothing_left_to_do_is_released_without_a_word_and_sleeps_where_it_is(owed):
    _stop(owed.other, owes=False)
    owed.rows = PERSONAL_CLEAR
    run(patrol.tick())
    assert owed.moved == [] and owed.sent == []
    assert (owed.other.account_id, owed.other.held_at) == ("work", None) and owed.other.sleep is not None


def test_a_tab_stopped_with_work_left_is_moved_and_told_to_carry_on_once(owed):
    _stop(owed.other, owes=True)
    owed.rows = PERSONAL_CLEAR
    run(patrol.tick())
    run(patrol.tick())
    [text] = _texts_to(owed, owed.other.id)
    assert owed.moved == [owed.other.id] and f'phase="{CONTINUE}" account="personal"' in text
    assert owed.other.held_at is None and owed.other.owes_carry_on is False


def test_a_stopped_tab_that_is_woken_owes_nothing_any_more(owed):
    _stop(owed.tab, owes=True)
    owed.rows = [usage_row(seven=90)]
    owed.tab.sleep = None                                             # the operator opened it
    owed.blocked_by = (PROCESSES_RUNNING,)                            # and runs a command in it
    run(patrol.tick())
    assert owed.tab.held_at is None and owed.tab.owes_carry_on is False


# --- a request that is no longer needed ---

def test_a_tab_asked_to_stop_and_then_not_stopped_is_told_to_carry_on_once_at_its_break(owed):
    owed.tab.owes_carry_on = True                                     # asked to stop; then personal fell under its line
    owed.rows = [usage_row(seven=10)]
    owed.blocked_by = (TURN_OPEN,)
    run(patrol.tick())
    assert _texts_to(owed, owed.tab.id) == []                         # still answering: it is waited for
    owed.blocked_by = ()
    run(patrol.tick())
    run(patrol.tick())
    [text] = _texts_to(owed, owed.tab.id)
    assert f'phase="{CONTINUE}"' in text and "止めずに" in text and owed.tab.owes_carry_on is False


def test_the_carry_on_waits_while_the_account_the_tab_runs_on_is_at_its_line(owed):
    owed.tab.owes_carry_on = True
    owed.rows = [usage_row(seven=90)]
    owed.sleep_reasons = ("turn_open",)                               # it cannot be put to sleep this look
    run(patrol.tick())
    assert _texts_to(owed, owed.tab.id) == [] and owed.tab.owes_carry_on is True


# --- what may wake a tab ---

def test_a_sleeping_tab_that_was_not_stopped_keeps_its_messages_while_no_account_is_clear(owed):
    owed.other.sleep = SleepMark(claude_sid="c1", record="/r.jsonl", slept_at=1)
    owed.rows = BOTH_AT_LINES
    assert hold_mail.must_keep(owed.other.id)
    owed.rows = PERSONAL_CLEAR
    assert not hold_mail.must_keep(owed.other.id)                     # it wakes on personal


@pytest.mark.parametrize("asleep, rows, expected", [
    (True, BOTH_AT_LINES, False),
    (True, PERSONAL_CLEAR, True),                                     # it wakes, and is moved, on personal
    (False, PERSONAL_CLEAR, False),                                   # awake on work at its line: the fallback moves it
    (False, [usage_row("work", seven=10), usage_row(seven=90)], True),
])
def test_a_tab_of_work_may_run_only_where_an_account_is_clear(owed, asleep, rows, expected):
    if asleep:
        owed.other.sleep = SleepMark(claude_sid="c1", record="/r.jsonl", slept_at=1)
    assert hold_mail.may_run(owed.other, rows, read_rules(), time.time()) is expected


def test_a_tab_of_personal_may_not_run_awake_on_personal_at_its_line(owed):
    assert hold_mail.may_run(owed.tab, [usage_row(seven=90)], read_rules(), time.time()) is False
    assert hold_mail.may_run(owed.tab, [usage_row(seven=10)], read_rules(), time.time()) is True
