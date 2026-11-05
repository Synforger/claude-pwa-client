"""Whether a stopped tab is told to carry on (`limit_resume/resume_judgement.py`)."""
from __future__ import annotations

from backend.limit_resume.resume_judgement import should_resume
from backend.sleep.record_facts import LimitStop
from backend.usage.limit_state import LimitState

STOP = LimitStop("lim1", at=1000.0)


def _state(at_limit=False, read_at=None, last_reset=None) -> LimitState:
    return LimitState(at_limit=at_limit, read_at=read_at, ends_at=None, last_reset=last_reset)


def test_a_window_that_was_at_the_line_and_reset_after_the_stop_ends_it():
    assert should_resume(stop=STOP, resumed=None, state=_state(last_reset=1500.0), seen_at_limit=False)


def test_a_reset_from_before_the_stop_does_not_explain_it():
    assert not should_resume(stop=STOP, resumed=None, state=_state(last_reset=900.0), seen_at_limit=True)


def test_a_newer_row_under_the_line_ends_a_stop_that_was_seen_at_the_line():
    assert should_resume(stop=STOP, resumed=None, state=_state(read_at=1200.0), seen_at_limit=True)


def test_a_stop_that_was_never_seen_at_the_line_is_not_answered_by_a_row_alone():
    assert not should_resume(stop=STOP, resumed=None, state=_state(read_at=1200.0), seen_at_limit=False)


def test_a_row_from_before_the_stop_proves_nothing():
    assert not should_resume(stop=STOP, resumed=None, state=_state(read_at=900.0), seen_at_limit=True)


def test_while_the_account_is_at_the_line_or_nothing_is_known_the_tab_waits():
    assert not should_resume(stop=STOP, resumed=None, state=_state(at_limit=True, read_at=1200.0), seen_at_limit=True)
    assert not should_resume(stop=STOP, resumed=None, state=None, seen_at_limit=True)


def test_a_stop_that_was_answered_is_not_answered_again():
    assert not should_resume(stop=STOP, resumed="lim1", state=_state(last_reset=1500.0), seen_at_limit=True)
    assert should_resume(stop=LimitStop("lim2", at=2000.0), resumed="lim1", state=_state(last_reset=2500.0),
                         seen_at_limit=False)
