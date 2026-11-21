"""The next state of a ticket's row for what a tab does to it, and the form of a due day. Pure: no file, no clock. Each
function gives the change to make from the row as it is NOW (= `ticket_service.write_entry` calls it under the ticket's lock,
so a change that landed since the caller looked, an `ask` for one, is not undone). Used by `ticket_service.py`,
`ticket_pass.py` and `relay_home.py`.
"""
from __future__ import annotations

import re
from collections.abc import Callable
from datetime import date

from backend.tickets.ticket_index import OPEN, WAITING, WAITING_OPERATOR, IndexRow

_DUE_FORM = re.compile(r"\d{4}-\d{2}-\d{2}")
#: What a change of the row is: fields of `IndexRow`, or a function that works them out from the row as it is
Change = dict | Callable[[IndexRow], dict]


def parse_due(text: str) -> str | None:
    """`text` as a due day (`YYYY-MM-DD`, a day that exists), or None when it is not one."""
    day = text.strip()
    if not _DUE_FORM.fullmatch(day):
        return None
    try:
        return date.fromisoformat(day).isoformat()
    except ValueError:
        return None


def after_add(*, waiting: bool, due: str | None) -> Callable[[IndexRow], dict]:
    """What `add` changes: the ticket is `waiting` with the mark and `open` without it (= adding moves a waiting ticket back to
    open), and `due` is set when given. A ticket that waits for the operator stays so, whatever was added: the operator's
    answer is what moves it, and only `due` changes."""
    def change(row: IndexRow) -> dict:
        moved = {} if row.status == WAITING_OPERATOR else {"status": WAITING if waiting else OPEN}
        return {**moved, **({"due": due} if due else {})}
    return change


def after_pass(holder: str) -> Callable[[IndexRow], dict]:
    """What `pass` changes: the holder, and a waiting ticket is open again (= the tab it was handed to acts on it). The
    operator handing a ticket that waits for the operator to a tab leaves its state."""
    def change(row: IndexRow) -> dict:
        return {"holder": holder, **({"status": OPEN} if row.status == WAITING else {})}
    return change
