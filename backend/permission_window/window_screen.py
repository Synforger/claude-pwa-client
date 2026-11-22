"""What Claude Code's screen shows, as far as a permission window is concerned. Pure: it reads no pane and no state.

`read_screen` takes the pane's text (escapes removed) and says whether it shows a window (a selection with a marked line
and no input box under it), the input box (the box Claude takes a message in) or neither. A text that only has numbers in
it (`1. Yes` / `2. No` in a reply) is not a window: the marked line is the dialog's own. `shows_command` says whether a
command is on the screen whole, which is the condition for answering a window the person has not read.

Used by `window_state.py` (the detector's looks), `window_answer.py` (the look before a key is typed) and
`window_judgement.py`.
"""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from enum import Enum

from backend._common.pane_choices import choices_in_pane


class ScreenKind(Enum):
    WINDOW = "window"
    INPUT = "input"
    OTHER = "other"


@dataclass(frozen=True)
class ScreenReading:
    """What one look at the pane showed: the kind, the choices of a window (`(key, label)`, top to bottom), the text of
    the dialog above them and a fingerprint of the lower part of the screen (it changes when another window is drawn)."""
    kind: ScreenKind
    choices: tuple[tuple[str, str], ...] = ()
    dialog_text: str = ""
    fingerprint: str = ""


# A horizontal rule: the border of the input box and of a dialog.
_RULE = re.compile(r"^\s*[─━]{8,}\s*$")
# The line the input box is typed on, which is not a numbered choice.
_PROMPT = re.compile(r"^\s*[❯>](?!\s*\d+\.)")
# The marked line of a selection.
_MARKED_CHOICE = re.compile(r"^\s*❯\s*\d+\.\s+\S")
# The side border a dialog may be drawn with.
_SIDE_BORDER = "│┃"
_FINGERPRINT_LINES = 12
LABEL_YES = "Yes"
LABEL_NO = "No"


def read_screen(plain: str) -> ScreenReading:
    """The reading of the pane's text `plain` (escapes removed)."""
    lines = [line.rstrip() for line in plain.split("\n")]
    marked = _last_index(lines, lambda line: bool(_MARKED_CHOICE.match(line)))
    box_end = _input_box_end(lines)
    fingerprint = hashlib.sha1("\n".join(lines[-_FINGERPRINT_LINES:]).encode("utf-8")).hexdigest()
    if marked is not None and (box_end is None or box_end < marked):
        choices = tuple((choice["key"], choice["label"]) for choice in choices_in_pane("\n".join(lines), selection_marker=True))
        return ScreenReading(ScreenKind.WINDOW, choices, _dialog_text(lines, marked), fingerprint)
    if box_end is not None:
        return ScreenReading(ScreenKind.INPUT, fingerprint=fingerprint)
    return ScreenReading(ScreenKind.OTHER, fingerprint=fingerprint)


def is_yes_no(reading: ScreenReading) -> bool:
    """Whether the window offers two choices and only two: `Yes` and `No`. Any other form (a third choice, a
    `Yes, and don't ask again`) is answered at the terminal."""
    return tuple(label for _key, label in reading.choices) == (LABEL_YES, LABEL_NO)


def shows_command(reading: ScreenReading, command: str) -> bool:
    """Whether the dialog on the screen shows the whole of `command`, spaces and line breaks aside. A command that is
    cut short on the screen is not shown whole, and neither is one the dialog is not read for (no rule above it)."""
    squashed = _squash(command)
    return bool(squashed) and squashed in _squash(reading.dialog_text)


def _squash(text: str) -> str:
    return re.sub(r"\s+", "", text.replace("│", " ").replace("┃", " "))


def _last_index(lines: list[str], matches) -> int | None:
    for index in range(len(lines) - 1, -1, -1):
        if matches(lines[index]):
            return index
    return None


def _input_box_end(lines: list[str]) -> int | None:
    """The line the last input box ends on (= its lower rule): two rules with the prompt line right under the upper one."""
    rules = [index for index, line in enumerate(lines) if _RULE.match(line)]
    for lower in range(len(rules) - 1, 0, -1):
        upper = rules[lower - 1]
        if upper + 1 < rules[lower] and _PROMPT.match(lines[upper + 1]):
            return rules[lower]
    return None


def _dialog_text(lines: list[str], marked: int) -> str:
    """The text of the dialog above its choices: the lines under the nearest rule above the first choice. Empty when
    there is no such rule (= the dialog is not read, so nothing on it is taken as shown)."""
    first = marked
    while first > 0 and re.match(r"^\s*(?:❯\s*)?\d+\.\s", lines[first - 1]):
        first -= 1
    rule = _last_index(lines[:first], lambda line: bool(_RULE.match(line)))
    if rule is None:
        return ""
    return "\n".join(line.strip(_SIDE_BORDER + " ") for line in lines[rule + 1:first])
