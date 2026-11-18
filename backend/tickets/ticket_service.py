"""What the doors of the tickets do: open a ticket, add to it, ask the operator through it, close it, read it and list
them. Every change goes through the guard's judgements first (`ticket_checks.py`) and is written by this process alone:
the lines to the ticket's file (`ticket_file.py`) and the row of the index (`ticket_index.py`) change together under
the ticket's lock. Handing a ticket to another tab is `ticket_pass.py`. Called by `routes/tickets.py`.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from pathlib import Path

from fastapi import HTTPException

from backend._common import config as _config
from backend._common import paths
from backend._common.errors import raise_error
from backend._common.state import sessions_meta
from backend.routes.agent_messages import last_operator_text
from backend.terminal.runner import jsonl_path_for_session
from backend.tickets import ticket_checks, ticket_entry, ticket_file, ticket_id, ticket_index, ticket_places
from backend.tickets.ticket_entry import Writer
from backend.tickets.ticket_index import CLOSED, OPEN, WAITING_OPERATOR, IndexRow

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


def write_entry(ticket: str, folder: Path, entry: dict, change: dict | None = None, *, must_be_open: bool = False) -> IndexRow:
    """Add a line and, with it, change the ticket's row (`change` = fields of `IndexRow`). A ticket that closed since the
    caller looked is refused here, which is the check that counts (= the lock is held). `must_be_open` refuses a ticket
    that waits for the operator as well. → the row after the change."""
    with ticket_file.lock_for(ticket), ticket_index.locked():
        row = row_of(ticket, open_only=True)
        if must_be_open and row.status == WAITING_OPERATOR:
            raise_error(409, "ticket_waiting_operator", f"その票は操作者の返事を待っています。 渡せません: {ticket}", id=ticket)
        ticket_file.append(folder, ticket, entry)
        if change:
            row = row._replace(**change)
            ticket_index.put(ticket, row)
        return row


def _create(folder: Path, opener: str, entries: list[dict]) -> str:
    """Give the next free id of this machine and day to a new ticket, write its first lines and its row. A file of that
    id left by an earlier run counts as taken."""
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
        ticket_index.put(candidate, IndexRow(key, opener, opener, OPEN, None))
    return candidate


async def open_ticket(sender: str, title: str, text: str, *, operator_said: bool) -> dict:
    """Open a ticket for the tab `sender`. With `operator_said`, the operator's last words in the tab (as the conversation's
    record has them, never as the tab says them) are the second line. The place is decided by the guard; the first lines
    are judged for it before anything is written.
    → `{"ok", "id", "place_outside", "operator_said"}` and, when the words were asked for and could not go in,
    `operator_said_left_out`."""
    said = last_operator_text(jsonl_path_for_session(sender)) if operator_said else None
    folder = await ticket_checks.decide_place(sender, sender if said else None)
    if folder != paths.TICKETS_DIR and not folder.parent.is_dir():
        raise_error(503, "ticket_place_unknown", "検査コマンドが答えた票の置き場の、 親の folder がありません")
    writer, at = writer_of(sender), now()
    entries = [ticket_entry.make_entry(ticket_entry.OPENED, writer, text, at=at, title=title)]
    if said:
        entries.append(ticket_entry.make_entry(ticket_entry.OPERATOR, writer, said, at=at, typed_in=sender))
    for entry in entries:
        await ticket_checks.check_write(folder, ticket_entry.judged_text(entry), sender if said else None)
    new_id = await asyncio.to_thread(_create, folder, sender, entries)
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


async def add(sender: str, ticket: str, text: str) -> dict:
    """Add what `sender` did to the ticket. It changes no row: the ticket stays with whoever holds it."""
    _row, folder = await _prepare(sender, ticket, text)
    row = await asyncio.to_thread(write_entry, ticket, folder,
                                  ticket_entry.make_entry(ticket_entry.ADDED, writer_of(sender), text, at=now()))
    return {"ok": True, "id": ticket, "status": row.status}


async def ask(sender: str, ticket: str, kind: str, text: str, recommend: str | None) -> dict:
    """Put the ticket in front of the operator: a `kind` (= one of `ticket_entry.ASK_KINDS`) of request, with the
    recommendation the operator may take as it stands. The ticket waits for the operator from here (`waiting-operator`)."""
    _row, folder = await _prepare(sender, ticket, f"{text}\n\n{recommend}" if recommend else text)
    extra = {"ask_kind": kind, **({"recommend": recommend} if recommend else {})}
    row = await asyncio.to_thread(
        write_entry, ticket, folder, ticket_entry.make_entry(ticket_entry.ASKED, writer_of(sender), text, at=now(), **extra),
        {"status": WAITING_OPERATOR, "wants": kind})
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
    judged). A ticket whose place is not known has no title."""
    summaries = []
    for ticket, row in ticket_index.rows().items():
        title, opened_at = None, None
        try:
            folder = await ticket_places.folder_for(row.place_key)
            first = next(iter(await asyncio.to_thread(ticket_file.read, folder, ticket)), {})
            title, opened_at = first.get("title"), first.get("at")
        except HTTPException as error:
            # the list still shows the ticket, without its title, when its place cannot be found now
            logger.info("ticket %s listed without its title: %s", ticket, error.detail)
        summaries.append({"id": ticket, "title": title, "opened_at": opened_at, "status": row.status, "wants": row.wants,
                          "holder": row.holder, "opener": row.opener,
                          "place_outside": row.place_key == ticket_places.outside_key()})
    return {"ok": True, "tickets": sorted(summaries, key=lambda s: (s["opened_at"] or "", s["id"]), reverse=True)}
