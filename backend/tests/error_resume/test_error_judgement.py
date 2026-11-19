"""Whether the client carries a tab on after a passing API error, waits, gives up or leaves it
(`error_resume/error_judgement.py`). Pure: every case is a call."""
from __future__ import annotations

import pytest

from backend._common.state import ErrorResumeMark
from backend.error_resume.error_judgement import (
    GIVE_UP, MAX_AGE_SEC, NONE, NOT_MINE, SEND, SEND_LIMIT, STREAK_LIMIT, UNTAKEN_SEC, WAIT, WAITS_BY_STREAK_SEC, judge,
)
from backend.sleep.record_facts import ErrorStop

NOW = 1_000_000.0


def _stop(age: float = 120.0) -> ErrorStop:
    return ErrorStop(uuid="e1", at=NOW - age, error="server_error", cause="", words="cut")


def _judge(**given) -> str:
    facts = dict(stop=_stop(), streak=0, resumed=None, gave_up=None, takes_asks=False, reported=False, held=False,
                 may_run=True, owes_other=False, asleep=False, claude_runs=True, at_break=True, now=NOW)
    facts.update(given)
    return judge(**facts)


def test_an_awake_tab_at_a_break_after_the_first_wait_is_sent_the_message():
    assert _judge() == SEND


def test_a_sleeping_tab_is_sent_it_too():
    assert _judge(asleep=True, claude_runs=False, at_break=False) == SEND


def test_no_stop_or_a_stop_given_up_on_is_nothing():
    assert _judge(stop=None) == NONE
    assert _judge(gave_up="e1") == NONE
    assert _judge(gave_up="older") == SEND


@pytest.mark.parametrize("given", [
    dict(stop=_stop(MAX_AGE_SEC + 1)), dict(takes_asks=True), dict(reported=True), dict(held=True),
    dict(may_run=False), dict(owes_other=True), dict(claude_runs=False, at_break=False),
])
def test_stops_another_feature_or_nobody_carries_on_are_not_the_clients(given):
    assert _judge(**given) == NOT_MINE


def test_a_tab_that_is_not_at_a_break_is_waited_for():
    assert _judge(at_break=False) == WAIT


@pytest.mark.parametrize("streak", range(STREAK_LIMIT))
def test_each_streak_waits_its_time_from_the_error(streak):
    wait = WAITS_BY_STREAK_SEC[streak]
    assert _judge(stop=_stop(wait - 1), streak=streak) == WAIT
    assert _judge(stop=_stop(wait + 1), streak=streak) == SEND


def test_the_streak_limit_gives_up_without_waiting():
    assert _judge(stop=_stop(1), streak=STREAK_LIMIT) == GIVE_UP


def test_a_message_just_sent_is_waited_for_then_sent_again_once_then_given_up():
    sent = ErrorResumeMark(stop="e1", sent_at=NOW - 10)
    assert _judge(resumed=sent) == WAIT
    late = ErrorResumeMark(stop="e1", sent_at=NOW - UNTAKEN_SEC - 1)
    assert _judge(resumed=late) == SEND
    twice = ErrorResumeMark(stop="e1", sent_at=NOW - UNTAKEN_SEC - 1, sent_count=SEND_LIMIT)
    assert _judge(resumed=twice) == GIVE_UP


def test_a_message_for_an_earlier_stop_does_not_count():
    assert _judge(resumed=ErrorResumeMark(stop="e0", sent_at=NOW - 10, sent_count=SEND_LIMIT)) == SEND
