"""The words `tabs new` takes and the `<child-start>` block it writes at the head of a child tab's first message.

    tabs new <title> <task file> [--model <name>] [--effort <level>]

The block names the child's tier, and, when given, the model and the effort the parent chose for it, one `key=value`
line each. The agent's launch script reads the block and takes only the values its own settings allow (falling back to
its default otherwise), so the client keeps no list of names: it only refuses a value that could break the block (= a
word of letters, digits, `.`, `_` and `-`). Pure: no file, no call. Used by `tabs.py`.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import NamedTuple

#: The options `tabs new` takes, each once, and the key each one writes in the block
OPTIONS = {"--model": "model", "--effort": "effort"}
#: What a value may be: one word that cannot end the block's line or open another
VALUE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")


class NewChild(NamedTuple):
    """What `tabs new` was asked to do. `settings` maps a block key (`model`, `effort`) to its value."""

    title: str
    file: Path
    settings: dict[str, str]


def parse_new(words: list[str]) -> NewChild | str | None:
    """The words after `new`. → the request, a reason a value is refused, or None when the words are not the form."""
    if len(words) < 2:
        return None
    settings: dict[str, str] = {}
    options = words[2:]
    while options:
        key = OPTIONS.get(options[0])
        if key is None or key in settings or len(options) < 2:
            return None
        if not VALUE.match(options[1]):
            return f"{options[0]} の値は英数字と . _ - の 1 語で書いてください: {options[1]!r}"
        settings[key], options = options[1], options[2:]
    return NewChild(words[0], Path(words[1]), settings)


def child_start_text(tier: str, settings: dict[str, str], task: str) -> str:
    """The child's first message: the block (tier first, then the chosen settings in a fixed order) and the task."""
    lines = [f"tier={tier}", *(f"{key}={settings[key]}" for key in OPTIONS.values() if key in settings)]
    return "<child-start>\n" + "\n".join(lines) + "\n</child-start>\n\n" + task
