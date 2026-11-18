"""The id of a ticket: `<machine>-<YYMMDD>-<NN>`, where NN counts from 01 per machine and day. The machine's name and the
year are in it so that two machines never give the same id and a ticket kept after it closed never meets the same day of
next year. The id is also a file name, so only ids of this form are taken from a caller. Pure.
"""
from __future__ import annotations

import re
from datetime import date

_ID_RE = re.compile(r"[A-Za-z0-9_-]+-\d{6}-\d{2,}")
_UNSAFE = re.compile(r"[^A-Za-z0-9_-]+")


def machine_part(name: str) -> str:
    """The machine's name as it is written in an id (= letters, digits, `_` and `-` only)."""
    return _UNSAFE.sub("-", name).strip("-") or "machine"


def ticket_id(machine: str, day: date, number: int) -> str:
    """The id of the `number`-th ticket of `machine` on `day`."""
    return f"{machine_part(machine)}-{day:%y%m%d}-{number:02d}"


def is_ticket_id(text: str) -> bool:
    """Whether `text` has the form of an id (= safe to use as a file name)."""
    return _ID_RE.fullmatch(text) is not None
