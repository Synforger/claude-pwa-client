"""Which children the watch looks at, why one stopped, and when its parent is told (`child_watch/watch_judgement.py`)."""
from __future__ import annotations

import pytest

import backend.child_watch.watch_judgement as j
from backend.child_watch.child_memo import WORKING

WATCHED = dict(child=True, parent_known=True, asleep=False, memo_state=WORKING)


def test_a_working_awake_child_of_a_known_parent_is_watched():
    assert j.is_watched(**WATCHED)


@pytest.mark.parametrize("change", [
    {"child": False},               # a fork or an ordinary tab
    {"parent_known": False},        # nobody to tell
    {"asleep": True},               # put to sleep by its parent or the sleep patrol
    {"memo_state": "完了"},          # it reported
    {"memo_state": "詰まり"},        # it reported
    {"memo_state": "?"},            # no memo, nothing says it works
])
def test_a_child_that_is_not_working_awake_and_known_is_not_watched(change):
    assert not j.is_watched(**{**WATCHED, **change})


def test_a_usage_limit_in_the_record_is_the_reason_limit_and_anything_else_is_idle():
    assert j.stop_reason(limit_stop=True, continuation_owed=False) == j.LIMIT
    assert j.stop_reason(limit_stop=False, continuation_owed=True) == j.LIMIT
    assert j.stop_reason(limit_stop=False, continuation_owed=False) == j.IDLE


@pytest.mark.parametrize("mark, previous, told, tell", [
    (100.0, None, None, False),     # first look at the stop
    (100.0, 100.0, None, True),     # the same stop on two looks in a row
    (100.0, 90.0, None, False),     # the child did something in between: a new stop, first look
    (None, 100.0, None, False),     # not at a break now
    (100.0, 100.0, 100.0, False),   # already told
    (200.0, 200.0, 100.0, True),    # told about an earlier stop; this one is new
])
def test_the_parent_is_told_on_the_second_look_in_a_row_and_once(mark, previous, told, tell):
    assert j.should_tell(mark=mark, previous=previous, told=told) is tell
