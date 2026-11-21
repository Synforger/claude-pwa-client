"""What the doors of the tickets do: open a ticket, add to it, ask the operator through it, close it, read it and list
them. Every change goes through the guard's judgements first (`ticket_checks.py`) and is written by this process alone:
the lines to the ticket's file (`ticket_file.py`) and the row of the index (`ticket_index.py`) change together under
the ticket's lock. Handing a ticket to another tab is `ticket_pass.py`. Called by `routes/tickets.py`.
"""
from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path

from fastapi import HTTPException

from backend._common import config as _config
from backend._common import paths
from backend._common.errors import raise_error
from backend._common.state import sessions_meta
from backend.routes.agent_messages import last_operator_text
from backend.terminal.runner import jsonl_path_for_session
from backend.tickets import (ticket_checks, ticket_entry, ticket_file, ticket_id, ticket_index, ticket_notify, ticket_places,
                             ticket_state, ticket_view, ticket_wake)
from backend.tickets.ticket_entry import Writer
from backend.tickets.ticket_index import CLOSED, OPEN, ORIGIN_OPERATOR, ORIGIN_SELF, WAITING_OPERATOR, IndexRow
from backend.tickets.ticket_state import Change

logger = logging.getLogger(__name__)

#: Why the operator's words did not go into a ticket that asked for them (= the answer's `operator_said_left_out`)
NO_OPERATOR_WORDS = "no_operator_words"


def now() -> str:
    """The time of a line: ISO in UTC with milliseconds, so that lines sort by it as text."""
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def writer_of(tab_id: str) -> Writer:
    """The tab as it is written in a line (= its name and tier as they are now)."""
    meta = sessions_meta[tab_id]
    return Writer(tab_id, meta.title, meta.tier or "")


def row_of(ticket: str, *, open_only: bool = False) -> IndexRow:
    """The index's row of a ticket. `ticket_unknown` when there is none; `ticket_closed` when `open_only` and it is closed."""
    row = ticket_index.get(ticket)
    if row is None:
        raise_error(404, "ticket_unknown", f"その id の票がありません: {ticket}", id=ticket)
    if open_only and row.status == CLOSED:
        raise_error(409, "ticket_closed", f"その票は閉じています。 書き足せません: {ticket}", id=ticket)
    return row


def write_entry(ticket: str, folder: Path, entry: dict, change: Change | None = None, *, must_be_open: bool = False,
                check: Callable[[IndexRow], None] | None = None, after: Callable[[], None] | None = None) -> IndexRow:
    """Add a line and, with it, change the ticket's row (`change` = fields of `IndexRow`, or a function that gives them from
    the row as it is under the lock: `ticket_state.py`). A ticket that closed since the
    caller looked is refused here, which is the check that counts (= the lock is held). `must_be_open` refuses a ticket
    that waits for the operator as well. `check` sees the row under the lock and raises to refuse the change, and `after`
    runs under the lock once the line and the row are written (= what must not be seen half done by another change).
    → the row after the change."""
    with ticket_file.lock_for(ticket), ticket_index.locked():
        row = row_of(ticket, open_only=True)
        if must_be_open and row.status == WAITING_OPERATOR:
            raise_error(409, "ticket_waiting_operator", f"その票は操作者の返事を待っています。 渡せません: {ticket}", id=ticket)
        if check is not None:
            check(row)
        ticket_file.append(folder, ticket, entry)
        fields = change(row) if callable(change) else change
        if fields:
            row = row._replace(**fields)
            ticket_index.put(ticket, row)
        if after is not None:
            after()
    ticket_wake.wake()
    return row


def record(ticket: str, folder: Path, entry: dict) -> None:
    """Add a line the client writes about what happened to the ticket (= `answered` is written by `write_entry`; this is
    for `delivered`). It changes no row and is let onto a closed ticket, since the operator's answer reaches the holder
    of a ticket that closed meanwhile."""
    with ticket_file.lock_for(ticket):
        ticket_file.append(folder, ticket, entry)
    ticket_wake.wake()


def _create(folder: Path, opener: str, entries: list[dict], origin: str, due: str | None) -> str:
    """Give the next free id of this machine and day to a new ticket, write its first lines and its row (= `origin` and `due`
    are set here and `origin` never again). A file of that id left by an earlier run counts as taken."""
    key = ticket_places.remember(folder)
    machine, today = _config.MACHINE_NAME, datetime.now().date()
    with ticket_index.locked():
        taken = ticket_index.rows()
        number = 1
        while True:
            candidate = ticket_id.ticket_id(machine, today, number)
            if candidate not in taken and ticket_file.create(folder, candidate, entries):
                break
            number += 1
        ticket_index.put(candidate, IndexRow(key, opener, opener, OPEN, None, origin, due))
    ticket_wake.wake()
    return candidate


async def open_ticket(sender: str, title: str, text: str, *, operator_said: bool, due: str | None = None) -> dict:
    """Open a ticket for the tab `sender`. With `operator_said`, the operator's last words in the tab (as the conversation's
    record has them, never as the tab says them) are the second line, and the ticket's `origin` is the operator's only when
    they went in. `due` is a day (`ticket_state.parse_due`). The place is decided by the guard; the first lines
    are judged for it before anything is written.
    → `{"ok", "id", "place_outside", "operator_said"}` and, when the words were asked for and could not go in,
    `operator_said_left_out`."""
    said = last_operator_text(jsonl_path_for_session(sender)) if operator_said else None
    folder = await ticket_checks.decide_place(sender, sender if said else None)
    if folder != paths.TICKETS_DIR and not folder.parent.is_dir():
        raise_error(503, "ticket_place_unknown", "検査コマンドが答えた票の置き場の、 親の folder がありません")
    writer, at = writer_of(sender), now()
    entries = [ticket_entry.make_entry(ticket_entry.OPENED, writer, text, at=at, title=title, **({"due": due} if due else {}))]
    if said:
        entries.append(ticket_entry.make_entry(ticket_entry.OPERATOR, writer, said, at=at, typed_in=sender))
    for entry in entries:
        await ticket_checks.check_write(folder, ticket_entry.judged_text(entry), sender if said else None)
    new_id = await asyncio.to_thread(_create, folder, sender, entries, ORIGIN_OPERATOR if said else ORIGIN_SELF, due)
    answer = {"ok": True, "id": new_id, "place_outside": folder == paths.TICKETS_DIR, "operator_said": bool(said)}
    return {**answer, "operator_said_left_out": NO_OPERATOR_WORDS} if operator_said and not said else answer


async def _prepare(sender: str, ticket: str, judged: str) -> tuple[IndexRow, Path]:
    """What every change needs first: the ticket is open, `sender` has read its place's boundary, and `judged` may be
    added there (= nothing is judged when it is empty)."""
    row = row_of(ticket, open_only=True)
    folder = await ticket_places.folder_for(row.place_key)
    await ticket_checks.check_covers(sender, folder)
    if judged.strip():
        await ticket_checks.check_write(folder, judged)
    return row, folder


async def add(sender: str, ticket: str, text: str, *, waiting: bool = False, due: str | None = None) -> dict:
    """Add what `sender` did to the ticket. The ticket stays with whoever holds it. Its state follows what was added
    (`ticket_state.after_add`): `waiting` sets it aside (the text says what it waits for), a plain line puts it back to open,
    and `due` is the day it is due."""
    _row, folder = await _prepare(sender, ticket, text)
    extra = {**({"waiting": True} if waiting else {}), **({"due": due} if due else {})}
    row = await asyncio.to_thread(write_entry, ticket, folder,
                                  ticket_entry.make_entry(ticket_entry.ADDED, writer_of(sender), text, at=now(), **extra),
                                  ticket_state.after_add(waiting=waiting, due=due))
    return {"ok": True, "id": ticket, "status": row.status}


def _refuse_unless_holder(sender: str, row: IndexRow) -> None:
    if row.holder != sender:
        raise_error(409, "ticket_not_holder", "この票を今持っているタブだけが、 操作者に訊けます")


async def ask(sender: str, ticket: str, kind: str, text: str, recommend: str | None) -> dict:
    """Put the ticket in front of the operator: a `kind` (= one of `ticket_entry.ASK_KINDS`) of request, with the
    recommendation the operator may take as it stands. The ticket waits for the operator from here (`waiting-operator`).
    Only the tab that holds the ticket may ask (`ticket_not_holder`): the operator's answer goes to the holder, so another
    tab's question would put the answer where nobody reads it. The operator's devices are told once it is asked."""
    row, folder = await _prepare(sender, ticket, f"{text}\n\n{recommend}" if recommend else text)
    _refuse_unless_holder(sender, row)
    extra = {"ask_kind": kind, **({"recommend": recommend} if recommend else {})}
    row = await asyncio.to_thread(
        write_entry, ticket, folder, ticket_entry.make_entry(ticket_entry.ASKED, writer_of(sender), text, at=now(), **extra),
        {"status": WAITING_OPERATOR, "wants": kind}, check=lambda current: _refuse_unless_holder(sender, current))
    ticket_notify.schedule(ticket, ticket_view.ATTENTION_WAITING)
    return {"ok": True, "id": ticket, "status": row.status}


async def close(sender: str, ticket: str, text: str) -> dict:
    """Close the ticket, with a last word when there is one. A closed ticket stays as the record of the request."""
    _row, folder = await _prepare(sender, ticket, text)
    row = await asyncio.to_thread(write_entry, ticket, folder,
                                  ticket_entry.make_entry(ticket_entry.CLOSED, writer_of(sender), text, at=now()),
                                  {"status": CLOSED, "wants": None})
    return {"ok": True, "id": ticket, "status": row.status}


async def show(reader: str, ticket: str) -> dict:
    """The ticket as the tab `reader` may read it: every line by time, the ones the guard does not let it read replaced."""
    row = row_of(ticket)
    folder = await ticket_places.folder_for(row.place_key)
    entries = await ticket_checks.filter_for_reader(reader, await asyncio.to_thread(ticket_file.read, folder, ticket))
    return {"ok": True, "id": ticket, "status": row.status, "wants": row.wants, "holder": row.holder,
            "opener": row.opener, "place_outside": row.place_key == ticket_places.outside_key(), "entries": entries}


async def list_tickets() -> dict:
    """Every ticket with its title, for the operator's screen (= read by the operator, who reads everything, so no line is
    judged). A ticket whose place is not known has no title. Each one carries what the screen sorts it by: the answers still on
    their way (`answer_pending`), the time of its last line (`last_at`), how its last delivery ended (`last_delivery`) and
    why it wants a look (`attention`, `ticket_view.attention`), and what the operator reads of it: where it came from
    (`origin`), the day it is due (`due`), the marks that say it needs another look (`marks`, `ticket_view.marks`) and the next
    step a tab last wrote (`next`, the first line of its last line: what `held` shows, so a ticket need not be opened to see
    what its tab is doing)."""
    summaries = []
    today, moment = datetime.now().date(), datetime.now(timezone.utc)
    for ticket, row in ticket_index.rows().items():
        entries: list[dict] = []
        try:
            folder = await ticket_places.folder_for(row.place_key)
            entries = await asyncio.to_thread(ticket_file.read, folder, ticket)
        except HTTPException as error:
            # the list still shows the ticket, without its title, when its place cannot be found now
            logger.info("ticket %s listed without its title: %s", ticket, error.detail)
        first = entries[0] if entries else {}
        delivery = ticket_view.last_delivery(entries)
        latest = ticket_view.latest_tab_line(entries)
        summaries.append({"id": ticket, "title": first.get("title"), "opened_at": first.get("at"), "status": row.status,
                          "wants": row.wants, "holder": row.holder, "opener": row.opener,
                          "place_outside": row.place_key == ticket_places.outside_key(),
                          "answer_pending": ticket_view.answer_pending(entries), "last_at": ticket_view.last_at(entries),
                          "last_delivery": delivery, "attention": ticket_view.attention(row.status, row.holder, delivery),
                          "origin": row.origin, "due": row.due,
                          "marks": ticket_view.marks(row.status, row.due, ticket_view.last_tab_time(entries), today, moment),
                          "next": ticket_view.first_line(latest.get("text")) if latest is not None else ""})
    return {"ok": True, "tickets": sorted(summaries, key=lambda s: (s["opened_at"] or "", s["id"]), reverse=True)}
