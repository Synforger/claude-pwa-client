"""Reads the numbered choices (`1. Yes`, `2. No`, ...) a Claude Code dialog shows at the end of the pane's text. Pure.

Used by `jsonl/plan_choices.py` (the plan approval) and `permission_window/window_screen.py` (the permission window).
"""
from __future__ import annotations

import re

# A choice line: `  1. Yes, auto-accept edits`.
_CHOICE_LINE = re.compile(r"^\s*(\d+)\.\s+(.+?)\s*$", re.MULTILINE)
# The same with the selection marker the dialog puts on the highlighted line (`❯ 1. Yes`).
_MARKED_CHOICE_LINE = re.compile(r"^\s*(?:❯\s*)?(\d+)\.\s+(.+?)\s*$", re.MULTILINE)


def choices_in_pane(text: str, *, selection_marker: bool = False) -> list[dict]:
    """The choices at the end of `text` (= the pane with its escapes removed): the last block of consecutive numbers
    counted down from the final one, each `{"key": "1", "label": "Yes"}`. A label stops at the first `(`, which opens an
    aside (`(esc to interrupt)`). Empty when the text shows no such block. `selection_marker` also reads the line the
    dialog highlights with `❯`, which the plan approval has never read."""
    pattern = _MARKED_CHOICE_LINE if selection_marker else _CHOICE_LINE
    choices: list[dict] = []
    seen_keys: set[str] = set()
    for match in pattern.finditer(text):
        key, label = match.group(1), match.group(2)
        if key in seen_keys:
            continue
        seen_keys.add(key)
        label = label.split("(")[0].strip()
        if label:
            choices.append({"key": key, "label": label})
    if len(choices) < 2:
        return choices
    tail: list[dict] = []
    for choice in reversed(choices):
        if tail and int(choice["key"]) != int(tail[-1]["key"]) - 1:
            break
        tail.append(choice)
    tail.reverse()
    return tail
