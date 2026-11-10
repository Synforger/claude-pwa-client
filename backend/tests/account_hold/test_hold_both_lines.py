"""When both accounts are at their lines: a tab of `work` (whose fallback is `personal`) is stopped on `work` instead of
being moved onto `personal`, it carries on on whichever account is clear first, and a message from another tab waits
instead of waking a stopped tab while no account is clear for it (`hold_patrol.py`, `hold_resume.py`, `hold_mail.py`).
The usage log, the sleep, the move and the message sent are the fixture's: `personal` holds its tabs at 70 % of the 7
days, `work` falls back to `personal` at 95 %."""
from __future__ import annotations

import pytest

from backend._common.state import SleepMark, sessions_meta
from backend.account_hold import hold_mail, hold_resume
from backend.account_hold import hold_patrol as patrol
from backend.account_hold.hold_envelope import CONTINUE, STOP
from backend.accounts.tab_claim import claimed
from backend.sleep.sleep_judgement import TURN_OPEN
from backend.tests.account_hold.conftest import accounts, usage_row
from backend.tests.async_run import run
from backend.tests.limit_samples import use_accounts

WORK_LINE_PCT = 95
BOTH_AT_LINES = "本来の口座も移す先の口座も使用量が線を超えたので"


@pytest.fixture
def both(env, monkeypatch):
    """`env.other` runs on `work`, which falls back to `personal`; moving a tab is done by the fixture (`env.moved`),
    to `personal` when it is on `work` and back to `work` when it was moved from there."""
    use_accounts(monkeypatch, accounts(work_fallback=WORK_LINE_PCT))
    monkeypatch.setattr(hold_mail, "read_all_rate_limits_tail", lambda: env.rows)

    async def _move(session_id):
        with claimed(session_id) as mine:
            if not mine:
                return
            env.moved.append(session_id)
            meta = sessions_meta[session_id]
            if meta.fallback_from is not None:
                meta.account_id, meta.fallback_from = meta.fallback_from, None
            else:
                meta.account_id, meta.fallback_from = "personal", meta.account_id

    monkeypatch.setattr(hold_resume, "move_before_wake", _move)
    return env


def _stop(meta) -> None:
    meta.held_at = 100.0
    meta.sleep = SleepMark(claude_sid="c1", record="/r.jsonl", slept_at=1)


def _texts_to(env, session_id) -> list[str]:
    return [text for sid, text in env.sent if sid == session_id]


# --- stopping ---

def test_a_tab_of_work_is_stopped_on_work_when_personal_is_at_its_line_too(both):
    both.rows = [usage_row("work", seven=96), usage_row(seven=90)]
    assert both.other.id in run(patrol.tick())
    assert (both.other.account_id, both.other.fallback_from) == ("work", None) and both.other.held_at is not None


def test_a_tab_of_work_at_its_line_is_left_to_the_fallback_while_personal_is_clear(both):
    both.rows = [usage_row("work", seven=96), usage_row(seven=10)]
    run(patrol.tick())
    assert both.other.held_at is None and (both.other.id, False) not in both.slept


def test_a_tab_of_work_is_left_alone_while_personal_s_usage_is_not_known(both):
    both.rows = [usage_row("work", seven=96)]
    run(patrol.tick())
    assert both.other.held_at is None


def test_a_tab_that_keeps_answering_is_told_it_carries_on_by_itself_when_either_account_is_clear(both):
    both.blocked_by = (TURN_OPEN,)
    both.rows = [usage_row("work", seven=96), usage_row(seven=90)]
    run(patrol.tick())
    [to_work] = _texts_to(both, both.other.id)
    [to_personal] = _texts_to(both, both.tab.id)
    assert f'phase="{STOP}" account="work"' in to_work and BOTH_AT_LINES in to_work
    assert BOTH_AT_LINES not in to_personal and "操作者が画面から続けた時" in to_personal   # personal's own tab


# --- carrying on on whichever account is clear first ---

def test_a_tab_stopped_on_work_moves_to_personal_and_carries_on_when_personal_is_clear_first(both):
    _stop(both.other)
    both.rows = [usage_row("work", seven=96), usage_row(seven=10)]
    run(patrol.tick())
    assert both.moved == [both.other.id]
    assert (both.other.account_id, both.other.fallback_from, both.other.held_at) == ("personal", "work", None)
    [text] = _texts_to(both, both.other.id)
    assert f'<account-hold phase="{CONTINUE}" account="personal">' in text


def test_a_tab_stopped_on_work_carries_on_there_when_work_is_clear_first(both):
    _stop(both.other)
    both.rows = [usage_row("work", seven=10), usage_row(seven=90)]
    run(patrol.tick())
    assert both.moved == [] and (both.other.account_id, both.other.held_at) == ("work", None)
    [text] = _texts_to(both, both.other.id)
    assert f'<account-hold phase="{CONTINUE}" account="work">' in text


def test_a_tab_stopped_on_work_stays_stopped_while_both_are_at_their_lines(both):
    _stop(both.other)
    both.rows = [usage_row("work", seven=96), usage_row(seven=90)]
    run(patrol.tick())
    assert both.moved == [] and both.sent == [] and both.other.held_at == 100.0


# --- messages to a stopped tab ---

def test_a_message_waits_while_no_account_is_clear_and_comes_after_the_continue(both):
    _stop(both.other)
    both.rows = [usage_row("work", seven=96), usage_row(seven=90)]
    assert hold_mail.must_keep(both.other.id)
    hold_mail.keep(both.other.id, "first")
    hold_mail.keep(both.other.id, "second")
    run(patrol.tick())
    assert both.sent == [] and both.other.kept_messages == ["first", "second"]
    both.rows = [usage_row("work", seven=96), usage_row(seven=10)]
    assert not hold_mail.must_keep(both.other.id)
    run(patrol.tick())
    texts = _texts_to(both, both.other.id)
    assert len(texts) == 3 and CONTINUE in texts[0] and texts[1:] == ["first", "second"]
    assert both.other.kept_messages == []


def test_a_message_to_a_stopped_tab_of_personal_itself_waits_until_personal_is_clear(both):
    _stop(both.tab)
    both.rows = [usage_row(seven=90)]
    assert hold_mail.must_keep(both.tab.id)
    hold_mail.keep(both.tab.id, "hello")
    run(patrol.tick())
    assert both.sent == []
    both.rows = [usage_row(seven=10)]
    run(patrol.tick())
    assert both.sent == [(both.tab.id, "hello")]                  # no continue: the operator continues such a tab


def test_a_stopped_tab_the_operator_woke_and_works_in_takes_its_kept_messages_at_the_next_look(both):
    _stop(both.tab)
    both.rows = [usage_row(seven=90)]
    hold_mail.keep(both.tab.id, "hello")
    both.tab.sleep = None                                          # the operator opened it
    both.blocked_by = (TURN_OPEN,)                                 # and it answers them
    assert not hold_mail.must_keep(both.tab.id)
    run(patrol.tick())
    assert (both.tab.id, "hello") in both.sent and both.tab.kept_messages == []


def test_a_woken_tab_that_is_stopped_again_at_its_break_keeps_its_messages(both):
    _stop(both.tab)
    both.rows = [usage_row(seven=90)]
    hold_mail.keep(both.tab.id, "hello")
    both.tab.sleep = None                                          # woken, but idle: the same look stops it again
    run(patrol.tick())
    assert both.tab.held_at is not None and both.sent == [] and both.tab.kept_messages == ["hello"]


def test_a_kept_message_that_is_not_taken_stays_first_for_the_next_look(both):
    _stop(both.tab)
    both.rows = [usage_row(seven=10)]
    hold_mail.keep(both.tab.id, "first")
    hold_mail.keep(both.tab.id, "second")
    both.deliver = False
    run(patrol.tick())
    assert both.tab.kept_messages == ["first", "second"]
    both.deliver = True
    run(patrol.tick())
    assert both.tab.kept_messages == [] and _texts_to(both, both.tab.id)[-2:] == ["first", "second"]


def test_a_message_to_a_tab_that_is_not_stopped_is_never_kept(both):
    both.rows = [usage_row("work", seven=96), usage_row(seven=90)]
    assert not hold_mail.must_keep(both.other.id)                  # running: it is stopped at its next break
    both.other.held_at = 100.0
    assert not hold_mail.must_keep(both.other.id)                  # stopped but awake
