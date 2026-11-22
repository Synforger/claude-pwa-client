"""What Claude Code's screen shows, as far as a permission window is concerned. Pure: it reads no pane and no state.

`read_screen` takes the pane's text (escapes removed) and says which of three it is:

- the input box: the last two horizontal rules of the screen (the upper one may carry a title) with a line that begins with
  `❯` or `>` right under the upper one (what is typed may begin with `1.` and is still the input box), and no footer line of
  a selection (`Esc to cancel`, `Esc to exit`, `Enter to select`, `Enter to confirm`) and no marked choice under it;
- a window: not the input box, with a marked choice (`❯ 1. Yes`) on the screen; a window drawn with a border on its sides is
  read with the border left out;
- neither.

Of a window it reads the choices (the run of numbered lines the marked one belongs to, labels whole) and the command field of
the dialog, which is cut by its indent: what a command holds is always drawn indented under the title, so a rule, a title
or a reason written inside a command is never an end of the field. `shows_command` is true only when that
field is the hook's command (and description) and nothing else, which is the condition for answering a window the person
has not read.

Used by `window_state.py` (the detector's looks), `window_answer.py` (the look before a key is typed) and
`window_judgement.py`.
"""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from enum import Enum
from itertools import takewhile


class ScreenKind(Enum):
    WINDOW = "window"
    INPUT = "input"
    OTHER = "other"


@dataclass(frozen=True)
class ScreenReading:
    """What one look at the pane showed: the kind, the choices of a window (`(key, label)`, top to bottom, labels whole), the
    command field of its dialog (None when the dialog could not be read) and a fingerprint of the lower part of the screen (it
    changes when another window is drawn)."""
    kind: ScreenKind
    choices: tuple[tuple[str, str], ...] = ()
    command_field: str | None = None
    fingerprint: str = ""


_RULE_CHARS = "─━"
_RULE_LENGTH_MIN = 8
# What the line the input is typed on begins with, whatever follows.
_PROMPT = re.compile(r"^[❯>]")
# The marked line of a selection, and a line of a selection.
_MARKED_CHOICE = re.compile(r"^❯\s*\d+\.\s+\S")
_CHOICE = re.compile(r"^(?:❯\s*)?(\d+)\.\s+(.+?)\s*$")
# The footer a selection draws under its choices.
_SELECTION_FOOTER = re.compile(r"Esc to cancel|Esc to exit|Enter to select|Enter to confirm", re.IGNORECASE)
# The line a hook's reason for asking is written on.
_HOOK_REASON = re.compile(r"^Hook \S")
# The title of the dialog that asks about a Bash command (`1 of 2` follows it when windows are queued).
_TITLE = re.compile(r"^Bash command(?:\s*\(?\d+ of \d+\)?)?$")
_SIDE_BORDER = "│┃"
_FINGERPRINT_LINES = 12
LABEL_YES = "Yes"
LABEL_NO = "No"


def read_screen(plain: str) -> ScreenReading:
    """The reading of the pane's text `plain` (escapes removed)."""
    drawn = [_inside_border(line) for line in plain.split("\n")]
    lines = [line.strip() for line in drawn]
    fingerprint = hashlib.sha1("\n".join(lines[-_FINGERPRINT_LINES:]).encode("utf-8")).hexdigest()
    if _input_box_shown(lines):
        return ScreenReading(ScreenKind.INPUT, fingerprint=fingerprint)
    marked = _last_index(lines, lambda line: bool(_MARKED_CHOICE.match(line)))
    if marked is None:
        return ScreenReading(ScreenKind.OTHER, fingerprint=fingerprint)
    first, choices = _choice_run(lines, marked)
    return ScreenReading(ScreenKind.WINDOW, choices, _command_field(drawn, first), fingerprint)


def is_yes_no(reading: ScreenReading) -> bool:
    """Whether the window offers two choices and only two: `Yes` and `No`, whole. Any other form (a third choice, a
    `Yes, and always allow`, a `Yes (always allow)`) is answered at the terminal."""
    return tuple(label for _key, label in reading.choices) == (LABEL_YES, LABEL_NO)


def shows_command(reading: ScreenReading, command: str, description: str | None = None) -> bool:
    """Whether the command field of the dialog on the screen is the hook's `command` (and its `description` when it has one),
    spaces and line breaks aside. A field that holds more or less than that (a command cut short, one with more before or
    after it, the reason's words) is not the command, and neither is a dialog that was not read."""
    expected = _squash(command + (description or ""))
    return bool(expected) and reading.command_field is not None and _squash(reading.command_field) == expected


def _squash(text: str) -> str:
    return re.sub(r"\s+", "", text)


def _inside_border(line: str) -> str:
    """The line as drawn inside a dialog's side border, its indent kept. Only a border in the first column is one: the same
    character further in is the text's own."""
    if line and line[0] in _SIDE_BORDER:
        return line[1:].removeprefix(" ").rstrip(_SIDE_BORDER + " ")
    return line.rstrip()


def _indent(line: str) -> int:
    return len(line) - len(line.lstrip())


def _last_index(lines: list[str], matches) -> int | None:
    for index in range(len(lines) - 1, -1, -1):
        if matches(lines[index]):
            return index
    return None


def _is_rule(line: str) -> bool:
    return line.startswith(tuple(_RULE_CHARS)) and sum(char in _RULE_CHARS for char in line) >= _RULE_LENGTH_MIN


def _input_box_shown(lines: list[str]) -> bool:
    """The last two rules of the screen frame a line that begins with a prompt, and no selection (its marked choice or its
    footer) is under them."""
    rules = [index for index, line in enumerate(lines) if _is_rule(line)]
    if len(rules) < 2:
        return False
    upper, lower = rules[-2], rules[-1]
    if lower <= upper + 1 or not _PROMPT.match(lines[upper + 1]):
        return False
    return not any(_SELECTION_FOOTER.search(line) or _MARKED_CHOICE.match(line) for line in lines[lower + 1:])


def _choice_run(lines: list[str], marked: int) -> tuple[int, tuple[tuple[str, str], ...]]:
    """The run of numbered lines the marked line is in, as `(index of its first line, ((key, label), ...))`: the numbers go
    up by one, a line indented under a choice goes with it, and a blank line or anything else ends the run."""
    choices = [_choice_of(lines[marked])]
    first = marked
    index = marked - 1
    while index >= 0 and lines[index] and not _is_rule(lines[index]):
        found = _CHOICE.match(lines[index])
        if found is None:
            break
        if int(found.group(1)) != int(choices[0][0]) - 1:
            break
        choices.insert(0, (found.group(1), found.group(2)))
        first = index
        index -= 1
    index = marked + 1
    while index < len(lines) and lines[index] and not _is_rule(lines[index]) and not _SELECTION_FOOTER.search(lines[index]):
        found = _CHOICE.match(lines[index])
        if found is not None:
            if int(found.group(1)) != int(choices[-1][0]) + 1:
                break
            choices.append((found.group(1), found.group(2)))
        index += 1
    return first, tuple(choices)


def _choice_of(line: str) -> tuple[str, str]:
    found = _CHOICE.match(line)
    assert found is not None     # the caller took it for a marked choice
    return found.group(1), found.group(2)


def _command_field(drawn: list[str], first_choice: int) -> str | None:
    """The command field of the dialog above its choices. The dialog's top is the nearest rule above that starts in the first
    column and the line under it is the title; the field is the lines under the title that are indented deeper, and what
    follows them, as deep as the title, is the hook's reason or the question right above the choices. None for any other
    shape: such a dialog is answered at the terminal."""
    top = _last_index(drawn[:first_choice], _is_rule)
    if top is None:
        return None
    body = [line for line in drawn[top + 1:first_choice] if line.strip()]
    if not body or not _TITLE.match(body[0].strip()):
        return None
    depth = _indent(body[0])
    field = list(takewhile(lambda line: _indent(line) > depth, body[1:]))
    after = body[1 + len(field):]
    if not field or not after or _indent(after[0]) != depth:
        return None
    if len(after) > 1 and not _HOOK_REASON.match(after[0].strip()):
        return None
    return "\n".join(line.strip() for line in field)
