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
#: What the client writes about a ticket (= no tab wrote it, so its `tab`, `tab_title` and `tier` are empty): the operator's
#: answer to one `asked` line, that answer reaching the holder, the holder going back to the tab that asked first, and the
#: operator having looked at an answer that did not arrive
ANSWERED = "answered"
DELIVERED = "delivered"
RETURNED = "returned"
SEEN = "seen"
#: What `tabs ticket ask --kind` takes: a decision from the operator, something only the operator at the Mac can do, a report
ASK_KINDS = ("decide", "mac", "report")
#: What a reader sees instead of a line it may not read (= the line's own kind is kept; nothing else of it is)
HIDDEN = "hidden"
HIDDEN_TEXT = "読めない境界の書き足し"
#: What a reader on another machine sees instead of the operator's own words: the line's kind and time are kept
WITHHELD_TEXT = "操作者の言葉は、 この機械の外へは出しません"


class Writer(NamedTuple):
    """The tab that writes a line."""

    tab: str
    tab_title: str
    tier: str


#: The writer of a line the client itself writes
CLIENT_WRITER = Writer("", "", "")


def make_entry(kind: str, writer: Writer, text: str, *, at: str, **extra: str | bool) -> dict:
    """A line of `kind` written by `writer` at `at` (= an ISO time in UTC, so that lines sort by their time).
    `extra` carries what only some kinds have: `title` (opened), `ask_kind` and `recommend` (asked), `to` (passed,
    delivered, returned), `typed_in` (operator), `asked_at` and `recommended` (answered), `asked_at` and `result`
    (delivered), `from` (returned)."""
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


def writer_text(entry: dict) -> str:
    """What the guard is shown of who wrote a line: the tab's name and tier, which say where it works. Empty when the
    line names nobody."""
    return "\n".join(str(entry[key]) for key in ("tab_title", "tier") if entry.get(key))


def without_writer(entry: dict, name: str) -> dict:
    """The line as a reader that may not know where its writer works is given it: `name` for the tab's name, and no tier."""
    return {**entry, "tab_title": name, "tier": ""}


def hidden(entry: dict) -> dict:
    """The line a reader that may not read `entry` is given in its place."""
    return {"kind": entry.get("kind", HIDDEN), "at": entry.get("at", ""), HIDDEN: True, "text": HIDDEN_TEXT}


def withheld(entry: dict) -> dict:
    """The line given to another machine in place of a line of the operator's own words."""
    return {"kind": entry.get("kind", HIDDEN), "at": entry.get("at", ""), HIDDEN: True, "text": WITHHELD_TEXT}
