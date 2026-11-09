"""A tab that keeps answering while its account is at the line is asked once to come to a break, and is moved and told
to carry on when it does (`fallback_patrol.py`, `fallback_judgement.py`, `fallback_envelope.py`)."""
from __future__ import annotations

import logging
import time

import pytest

import backend.account_fallback.fallback_patrol as patrol
from backend._common.state import SleepMark, sessions_meta
from backend.account_fallback.fallback_envelope import PAUSE, carry_on_envelope, pause_envelope
from backend.account_fallback.fallback_judgement import Move, pause_overdue, should_ask_to_pause
from backend.jsonl.jsonl_predicates import CLIENT_NOTICE_OPENING
from backend.tests.account_fallback.conftest import usage_row
from backend.tests.async_run import run
from backend.tests.limit_samples import use_accounts

ANSWERING = ("turn_open",)


@pytest.fixture
def answering(env):
    """The tab keeps answering while its account is at the line."""
    env.rows = [usage_row(five=96)]
    env.blocked_by = ANSWERING
    return env


def _asks(env) -> list[str]:
    return [text for _sid, text in env.sent if 'phase="pause"' in text]


def test_a_tab_that_keeps_answering_at_the_line_is_asked_once_whatever_the_number_of_looks(answering, caplog):
    with caplog.at_level(logging.INFO):
        for _ in range(3):
            assert run(patrol.tick()) == []
    [(session_id, text)] = answering.sent
    assert session_id == answering.tab.id
    assert text.splitlines()[0] == CLIENT_NOTICE_OPENING
    assert '<account-move phase="pause" from="work" to="personal">' in text
    assert "このタブを Personal の口座へ移します" in text
    assert "移した後に、続きを頼む連絡が届きます" in text
    assert answering.tab.account_id == "work" and answering.events == []
    logged = [r.getMessage() for r in caplog.records if "asked to pause" in r.getMessage()]
    assert logged == [f"account fallback: asked to pause session={answering.tab.id} account=work"]


def test_the_request_is_not_sent_again_after_the_backend_restarts(answering, isolated_state):
    run(patrol.tick())
    assert len(answering.sent) == 1
    stored = isolated_state._load_sessions_meta()[answering.tab.id]              # what a restart reads back
    assert stored.pause_asked_at == answering.tab.pause_asked_at is not None
    patrol._last_blocked.clear()
    patrol._gave_up_on.clear()
    run(patrol.tick())
    assert len(answering.sent) == 1


def test_a_request_that_was_not_delivered_is_made_again_at_the_next_look(answering, monkeypatch):
    delivered = patrol.send_to_tab

    async def _refuse(_session_id, _text):
        return False
    monkeypatch.setattr(patrol, "send_to_tab", _refuse)
    run(patrol.tick())
    assert answering.tab.pause_asked_at is None and answering.sent == []
    monkeypatch.setattr(patrol, "send_to_tab", delivered)
    run(patrol.tick())
    assert len(answering.sent) == 1 and answering.tab.pause_asked_at is not None


@pytest.mark.parametrize("held_by", [("processes_running",), ("wakeup_scheduled",), ("voice_call",), ()])
def test_a_tab_held_by_something_other_than_its_answer_is_not_asked(answering, held_by):
    answering.blocked_by = held_by
    run(patrol.tick())
    assert _asks(answering) == [] and answering.tab.pause_asked_at is None


def test_a_pinned_tab_is_not_asked(answering):
    answering.tab.account_pinned = True
    run(patrol.tick())
    assert answering.sent == []


def test_a_tab_asleep_is_not_asked(answering):
    answering.tab.sleep = SleepMark(claude_sid="OLD", record=str(answering.src), slept_at=int(time.time()),
                                    account_id="work")
    run(patrol.tick())
    assert answering.sent == []


def test_a_tab_a_limit_stopped_is_moved_and_not_asked(answering):
    answering.stopped()
    answering.blocked_by = ()                                          # a stop leaves no `turn_open` behind
    assert run(patrol.tick()) == [answering.tab.id]
    assert _asks(answering) == []
    assert 'reason="limit"' in answering.sent[0][1]


def test_a_tab_is_not_asked_while_the_usage_is_under_the_line_or_the_account_has_no_fallback(answering, monkeypatch):
    answering.rows = [usage_row(five=94)]
    run(patrol.tick())
    use_accounts(monkeypatch, {"personal": {"env": {}}, "work": {"env": {"CLAUDE_CONFIG_DIR": "/nonexistent-work"}}})
    answering.rows = [usage_row(five=100)]
    run(patrol.tick())
    assert answering.sent == []


def test_a_tab_on_the_fallback_account_is_not_asked(answering):
    answering.tab.account_id, answering.tab.fallback_from = "personal", "work"
    run(patrol.tick())
    assert answering.sent == []


def test_a_tab_that_comes_to_a_break_after_the_request_is_moved_and_told_to_carry_on(answering):
    run(patrol.tick())
    answering.blocked_by = ()
    assert run(patrol.tick()) == [answering.tab.id]
    assert (answering.tab.account_id, answering.tab.fallback_from) == ("personal", "work")
    assert answering.tab.pause_asked_at is None
    [(_sid, ask), (session_id, text)] = answering.sent
    assert session_id == answering.tab.id
    assert text == carry_on_envelope("work", "personal", PAUSE)
    assert text.splitlines()[0] == CLIENT_NOTICE_OPENING
    assert '<account-move from="work" to="personal" reason="pause">' in text
    assert "口座を移しました。止める前の作業を続けてください" in text
    assert 'phase="pause"' in ask


def test_a_tab_that_was_not_asked_is_moved_at_a_break_without_a_word(answering):
    answering.blocked_by = ()
    assert run(patrol.tick()) == [answering.tab.id]
    assert answering.sent == []


def test_a_tab_asked_and_then_woken_from_sleep_is_moved_and_forgotten(answering):
    run(patrol.tick())
    answering.tab.sleep = SleepMark(claude_sid="OLD", record=str(answering.src), slept_at=int(time.time()),
                                    account_id="work")
    run(patrol.move_before_wake(answering.tab.id))
    assert answering.tab.account_id == "personal" and answering.tab.pause_asked_at is None


def test_the_mark_goes_when_the_usage_falls_under_the_line_and_the_next_time_over_the_line_asks_again(answering):
    run(patrol.tick())
    answering.rows = [usage_row(five=50)]
    run(patrol.tick())
    assert answering.tab.pause_asked_at is None
    answering.rows = [usage_row(five=97)]
    run(patrol.tick())
    assert len(_asks(answering)) == 2


def test_the_mark_goes_when_the_tab_is_pinned_after_it_was_asked(answering):
    run(patrol.tick())
    answering.tab.account_pinned = True
    run(patrol.tick())
    assert answering.tab.pause_asked_at is None


def test_a_tab_that_does_not_come_to_a_break_in_ten_minutes_is_not_asked_again_and_the_log_says_so_once(
        answering, caplog):
    run(patrol.tick())
    answering.tab.pause_asked_at = time.time() - 601
    with caplog.at_level(logging.INFO):
        run(patrol.tick())
        run(patrol.tick())
    assert len(_asks(answering)) == 1
    gave_up = [r.getMessage() for r in caplog.records if "no break after asking" in r.getMessage()]
    assert len(gave_up) == 1 and f"session={answering.tab.id}" in gave_up[0]


def test_a_tab_not_yet_overdue_is_waited_for_without_a_word_in_the_log(answering, caplog):
    run(patrol.tick())
    with caplog.at_level(logging.INFO):
        run(patrol.tick())
    assert not [r for r in caplog.records if "no break after asking" in r.getMessage()]


def test_the_request_is_asked_only_of_a_tab_that_is_wanted_elsewhere_and_is_answering():
    ask = dict(wanted=Move.MOVE, blocked_by=("turn_open", "processes_running"), stopped_by_limit=False, asked_at=None)
    assert should_ask_to_pause(**ask) is True
    assert should_ask_to_pause(**{**ask, "wanted": Move.RETURN}) is True       # off an account that reached its own line
    assert should_ask_to_pause(**{**ask, "wanted": Move.STAY}) is False
    assert should_ask_to_pause(**{**ask, "blocked_by": ("processes_running",)}) is False
    assert should_ask_to_pause(**{**ask, "stopped_by_limit": True}) is False
    assert should_ask_to_pause(**{**ask, "asked_at": 1.0}) is False


def test_a_request_is_overdue_after_ten_minutes():
    assert pause_overdue(1000.0, 1000.0 + 599) is False and pause_overdue(1000.0, 1000.0 + 600) is True


def test_the_request_begins_with_the_client_s_line_and_names_the_account_by_its_display_name():
    text = pause_envelope("work", "personal", "Personal")
    assert text.splitlines()[0] == CLIENT_NOTICE_OPENING
    assert text.splitlines()[1] == '<account-move phase="pause" from="work" to="personal">'


def test_the_mark_is_stored_with_the_tab(answering):
    run(patrol.tick())
    assert sessions_meta[answering.tab.id].to_dict()["pause_asked_at"] == answering.tab.pause_asked_at
