"""The table of the design (W1 to W8): what is done with what a caller types, by the screen, the record's kind and who types
(`permission_window/window_judgement.py`). Each row of the table is a test."""
from __future__ import annotations

import pytest

from backend.permission_window.window_judgement import Action, Caller, Kind, Situation, judge
from backend.permission_window.window_screen import ScreenKind

WINDOW, INPUT, OTHER = ScreenKind.WINDOW, ScreenKind.INPUT, ScreenKind.OTHER
TYPE, HOLD, REFUSE, NOT_TYPED = Action.TYPE, Action.HOLD, Action.REFUSE, Action.NOT_TYPED


def at(screen, kind, **rest):
    return Situation(screen, kind, **rest)


# A message of a person or another tab, a command of the client, an answer to a question or a plan, a chip, an answer to an
# approval: what each is given at each row of the design's table.
ROWS = [
    # W1: a window, the call is an approval, the command is on the screen, Yes / No only
    ("W1", at(WINDOW, Kind.APPROVAL, answerable=True),
     {Caller.MESSAGE: HOLD, Caller.COMMAND: REFUSE, Caller.ANSWER: TYPE, Caller.CHOICE_ANSWER: REFUSE, Caller.CHIP: REFUSE}),
    # W2: the same window, but the command does not match / cannot be read / three choices / no hook input
    ("W2", at(WINDOW, Kind.APPROVAL, answerable=False),
     {Caller.MESSAGE: HOLD, Caller.COMMAND: REFUSE, Caller.ANSWER: NOT_TYPED, Caller.CHOICE_ANSWER: REFUSE, Caller.CHIP: REFUSE}),
    # W3: a window, the call is a question or a plan
    ("W3 question", at(WINDOW, Kind.QUESTION),
     {Caller.MESSAGE: HOLD, Caller.COMMAND: REFUSE, Caller.ANSWER: NOT_TYPED, Caller.CHOICE_ANSWER: TYPE, Caller.CHIP: TYPE}),
    ("W3 plan", at(WINDOW, Kind.PLAN),
     {Caller.MESSAGE: HOLD, Caller.COMMAND: REFUSE, Caller.ANSWER: NOT_TYPED, Caller.CHOICE_ANSWER: TYPE, Caller.CHIP: TYPE}),
    # W4: a window, no call (a picker, a window nothing is known of)
    ("W4", at(WINDOW, Kind.NONE),
     {Caller.MESSAGE: REFUSE, Caller.COMMAND: REFUSE, Caller.ANSWER: NOT_TYPED, Caller.CHOICE_ANSWER: REFUSE, Caller.CHIP: TYPE}),
    # W5: the input box on two looks, whatever the record says
    ("W5 nothing kept", at(INPUT, Kind.APPROVAL, input_looks=2),
     {Caller.MESSAGE: TYPE, Caller.COMMAND: TYPE, Caller.ANSWER: NOT_TYPED, Caller.CHOICE_ANSWER: REFUSE, Caller.CHIP: TYPE}),
    ("W5 messages kept", at(INPUT, Kind.NONE, input_looks=2, backlog=True),
     {Caller.MESSAGE: Action.RELEASE_THEN_TYPE, Caller.COMMAND: TYPE, Caller.ANSWER: NOT_TYPED,
      Caller.CHOICE_ANSWER: REFUSE, Caller.CHIP: TYPE}),
    # W6: the input box on the first look, or the screen redrawn halfway
    ("W6 input box first look, nothing kept", at(INPUT, Kind.NONE, input_looks=1),
     {Caller.MESSAGE: TYPE, Caller.COMMAND: TYPE, Caller.ANSWER: NOT_TYPED, Caller.CHOICE_ANSWER: REFUSE, Caller.CHIP: TYPE}),
    ("W6 input box first look, messages kept", at(INPUT, Kind.NONE, input_looks=1, backlog=True),
     {Caller.MESSAGE: HOLD, Caller.COMMAND: TYPE, Caller.ANSWER: NOT_TYPED, Caller.CHOICE_ANSWER: REFUSE, Caller.CHIP: TYPE}),
    ("W6 redrawn halfway, messages kept", at(OTHER, Kind.NONE, backlog=True),
     {Caller.MESSAGE: HOLD, Caller.COMMAND: TYPE, Caller.ANSWER: NOT_TYPED, Caller.CHOICE_ANSWER: TYPE, Caller.CHIP: TYPE}),
    ("W6 redrawn halfway, nothing kept", at(OTHER, Kind.NONE),
     {Caller.MESSAGE: TYPE, Caller.COMMAND: TYPE, Caller.ANSWER: NOT_TYPED, Caller.CHOICE_ANSWER: TYPE, Caller.CHIP: TYPE}),
]


@pytest.mark.parametrize("name, situation, expected", ROWS, ids=[row[0] for row in ROWS])
def test_each_row_of_the_table(name, situation, expected):
    assert {caller: judge(caller, situation) for caller in Caller} == expected


def test_w7_the_screen_that_turns_into_a_window_while_typing_keeps_the_message_and_refuses_the_command():
    """The look before the Enter reads the screen again: a window now is judged as W1 to W4, with the message at an approval
    kept and no key typed."""
    now_a_window = at(WINDOW, Kind.APPROVAL)
    assert judge(Caller.MESSAGE, now_a_window) is HOLD
    assert judge(Caller.COMMAND, now_a_window) is REFUSE


def test_the_messages_are_released_only_after_the_input_box_on_two_looks_in_a_row():
    for looks, expected in ((0, HOLD), (1, HOLD), (2, Action.RELEASE_THEN_TYPE), (5, Action.RELEASE_THEN_TYPE)):
        assert judge(Caller.MESSAGE, at(INPUT, Kind.NONE, input_looks=looks, backlog=True)) is expected


def test_a_window_the_client_does_not_remember_is_still_a_window():
    """What decides is the screen: no hook, no remembered window, no `answerable` is needed for a message to be kept."""
    assert judge(Caller.MESSAGE, at(WINDOW, Kind.APPROVAL, answerable=False)) is HOLD
