"""What to do with something typed at a tab when Claude Code may have a window open: type it, keep it, refuse it. Pure.

The cases are the table of the design (`docs/reference/permission-window.md`): the screen (a window / the input box / neither),
the kind of the call the record leaves without a result (an approval, a question, a plan, none), who types (a message to
keep, a command, an answer to a question or a plan, a chip, an answer to an approval) and what is kept already.

Used by `window_answer.py` (the look before every key typed into a tab) and `terminal/routes.py`.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from backend.permission_window.window_screen import ScreenKind

# How many looks in a row must show the input box before the messages kept are typed.
INPUT_LOOKS_TO_RELEASE = 2


class Kind(Enum):
    """What the record's oldest call without a result is: an approval (any tool but the next two), a question
    (`AskUserQuestion`), a plan to approve (`ExitPlanMode`), or no call at all."""
    NONE = "none"
    APPROVAL = "approval"
    QUESTION = "question"
    PLAN = "plan"


class Caller(Enum):
    """Who types: a person's text or another tab's message (kept while a window is open), the client's own commands (a
    rollover, a move of account, a notice, a child's first message, an ask: refused), a person's answer to a question or
    a plan (`answers_choice`), a chip or a single digit, and an answer to an approval (the door or an answer word)."""
    MESSAGE = "message"
    COMMAND = "command"
    CHOICE_ANSWER = "choice_answer"
    CHIP = "chip"
    ANSWER = "answer"


class Action(Enum):
    TYPE = "type"
    RELEASE_THEN_TYPE = "release_then_type"
    HOLD = "hold"
    REFUSE = "refuse"
    NOT_TYPED = "not_typed"


@dataclass(frozen=True)
class Situation:
    """What the judgement reads: the screen, the record's kind, whether the window on the screen may be answered by a
    key (`answerable`), how many looks in a row showed the input box and whether messages are kept."""
    screen: ScreenKind
    kind: Kind
    answerable: bool = False
    input_looks: int = 0
    backlog: bool = False


class WindowInTheWay(Exception):
    """Raised before a key is typed when the judgement says not to type it: `action` is what the caller does instead."""

    def __init__(self, action: Action) -> None:
        super().__init__(action.value)
        self.action = action


def judge(caller: Caller, situation: Situation) -> Action:
    """What to do with what `caller` is about to type, in `situation`."""
    if situation.screen is ScreenKind.WINDOW:
        return _at_window(caller, situation)
    return _off_window(caller, situation)


def _at_window(caller: Caller, situation: Situation) -> Action:
    kind = situation.kind
    if caller is Caller.ANSWER:
        return Action.TYPE if kind is Kind.APPROVAL and situation.answerable else Action.NOT_TYPED
    if caller is Caller.COMMAND:
        return Action.REFUSE
    if caller is Caller.CHIP:
        return Action.REFUSE if kind is Kind.APPROVAL else Action.TYPE
    if caller is Caller.CHOICE_ANSWER:
        return Action.TYPE if kind in (Kind.QUESTION, Kind.PLAN) else Action.REFUSE
    return Action.REFUSE if kind is Kind.NONE else Action.HOLD


def _off_window(caller: Caller, situation: Situation) -> Action:
    if caller is Caller.ANSWER:
        return Action.NOT_TYPED
    if caller is Caller.CHOICE_ANSWER:
        return Action.REFUSE if situation.screen is ScreenKind.INPUT else Action.TYPE
    if caller is not Caller.MESSAGE or not situation.backlog:
        return Action.TYPE
    if situation.screen is ScreenKind.INPUT and situation.input_looks >= INPUT_LOOKS_TO_RELEASE:
        return Action.RELEASE_THEN_TYPE
    return Action.HOLD
