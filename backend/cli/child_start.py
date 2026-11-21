"""The words `tabs new` takes and the `<child-start>` block it writes at the head of a child tab's first message.

    tabs new <title> <task file> [--model <name>] [--effort <level>]

The block names the child's tier, and, when given, the model and the effort the parent chose for it, one `key=value`
line each. The agent's launch script reads the block and takes only the values its own settings allow (falling back to
its default otherwise), so the client keeps no list of names: it only refuses a value that could break the block (= a
word of letters, digits, `.`, `_` and `-`).

The backend reads the chosen settings back from the block when it opens the child (`routes/child_sessions.py`), keeps
them on the tab's record, and writes the same lines into the envelope of the child's rollover (`routes/rollover.py`),
so that a child started again keeps what its parent chose. Pure: no file, no call. Used by `tabs.py` and those two.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import NamedTuple

#: The options `tabs new` takes, each once, and the key each one writes in the block
OPTIONS = {"--model": "model", "--effort": "effort"}
#: What a value may be: one word that cannot end the block's line or open another
VALUE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
#: The block at the head of a child's first message, and what is inside it
BLOCK = re.compile(r"<child-start>\n(.*?)\n</child-start>", re.S)


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


def settings_lines(settings: dict[str, str]) -> list[str]:
    """The `key=value` lines of the chosen settings, in a fixed order (= model, then effort). A value that is not one
    word is left out, so that a stored value can never break the block or the envelope it is written into."""
    return [f"{key}={settings[key]}" for key in OPTIONS.values()
            if isinstance(settings.get(key), str) and VALUE.match(settings[key])]


def child_start_text(tier: str, settings: dict[str, str], task: str) -> str:
    """The child's first message: the block (tier first, then the chosen settings in a fixed order) and the task."""
    lines = [f"tier={tier}", *settings_lines(settings)]
    return "<child-start>\n" + "\n".join(lines) + "\n</child-start>\n\n" + task


def read_settings(text: str) -> dict[str, str]:
    """The settings the block at the head of `text` carries (= what `child_start_text` wrote). Empty when `text` does
    not start with the block; a line of another key, or with a value that is not one word, is left out."""
    found = BLOCK.match(text.lstrip())
    if found is None:
        return {}
    pairs = (line.partition("=") for line in found.group(1).splitlines())
    keys = set(OPTIONS.values())
    return {key: value for key, sep, value in pairs if sep and key in keys and VALUE.match(value)}
