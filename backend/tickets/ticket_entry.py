"""One line of a ticket: the kinds of line, how one is made, written and read back, and what a reader who may not read
it is shown instead. Pure: no file and no clock (= the caller passes the time). Used by `ticket_file.py`, `ticket_checks.py`
and `ticket_service.py`.
"""
from __future__ import annotations

import json
from typing import NamedTuple

OPENED = "opened"
OPERATOR = "operator"
ADDED = "added"
ASKED = "asked"
PASSED = "passed"
CLOSED = "closed"
#: What `tabs ticket ask --kind` takes: a decision from the operator, something only the operator at the Mac can do, a report
ASK_KINDS = ("decide", "mac", "report")
#: What a reader sees instead of a line it may not read (= the line's own kind is kept; nothing else of it is)
HIDDEN = "hidden"
HIDDEN_TEXT = "読めない境界の書き足し"


class Writer(NamedTuple):
    """The tab that writes a line."""

    tab: str
    tab_title: str
    tier: str


def make_entry(kind: str, writer: Writer, text: str, *, at: str, **extra: str) -> dict:
    """A line of `kind` written by `writer` at `at` (= an ISO time in UTC, so that lines sort by their time).
    `extra` carries what only some kinds have: `title` (opened), `ask_kind` and `recommend` (asked), `to` (passed),
    `typed_in` (operator)."""
    return {"kind": kind, "at": at, "tab": writer.tab, "tab_title": writer.tab_title, "tier": writer.tier, "text": text,
            **extra}


def to_line(entry: dict) -> str:
    """The line as written in the file: one JSON object and a newline."""
    return json.dumps(entry, ensure_ascii=False) + "\n"


def parse_lines(raw: str) -> list[dict]:
    """The lines of a ticket file as entries, by time (= ties keep the order they were written in). A line that is not a
    JSON object is left out."""
    entries = []
    for line in raw.splitlines():
        try:
            entry = json.loads(line)
        except ValueError:
            continue
        if isinstance(entry, dict):
            entries.append(entry)
    return sorted(entries, key=lambda entry: str(entry.get("at", "")))


def judged_text(entry: dict) -> str:
    """What the guard is shown of a line: its text, and for the first line its title too (= a title is content like
    any other)."""
    title = entry.get("title")
    return f"{title}\n\n{entry.get('text', '')}" if isinstance(title, str) and title else str(entry.get("text", ""))


def hidden(entry: dict) -> dict:
    """The line a reader that may not read `entry` is given in its place."""
    return {"kind": entry.get("kind", HIDDEN), "at": entry.get("at", ""), HIDDEN: True, "text": HIDDEN_TEXT}
