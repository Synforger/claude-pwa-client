"""The tickets a tab holds, as the tab asks for them (`tabs ticket mine`): every ticket that is not closed and that the index
names the tab as holder of, from this machine and from the other machine's list, each with what the tab may read of its title and
its last line (`filter_for_reader`, as `show` does: a title the tab may not read is not given), the marks that say it needs
another look, whether the tab itself has written since a time and whether it may still write there (`check_covers`). A
machine that does not answer is named and left out; it does not stop the list. Called by `routes/tickets.py`.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import date, datetime, timezone
from pathlib import Path

from fastapi import HTTPException

from backend._common import config as _config
from backend._common import paths
from backend.peers.peer_call import PEER_LIST_TIMEOUT_SEC, TICKETS_PATH, call_peer
from backend.routes.agent_messages import allowed_for_peer
from backend.tickets import ticket_checks, ticket_file, ticket_index, ticket_places, ticket_relay, ticket_view
from backend.tickets.ticket_index import CLOSED, ORIGIN_SELF
from backend.tickets.ticket_relay import Home

logger = logging.getLogger(__name__)


async def held_by(tab: str, since: str | None) -> dict:
    """The tickets the tab `tab` holds, by id, and the machines that did not answer. `since` is the time from which a line of the
    tab's own counts as written (`written_since`); without it that field is null.
    → `{"ok", "tab", "tickets": [...], "peer_unreachable": [<machine>, ...]}`."""
    today, now = datetime.now().date(), datetime.now(timezone.utc)
    local = [await _local(tab, ticket, row, since, today, now) for ticket, row in sorted(ticket_index.rows().items())
             if row.holder == tab and row.status != CLOSED]
    elsewhere, unreachable = [], []
    for name, peer in _config.AGENT_MESSAGE_PEERS.items():
        if not allowed_for_peer(peer, tab):
            continue
        try:
            elsewhere += await _on_machine(Home(name, peer), tab, since, today, now)
        except HTTPException as error:
            logger.info("held by %s: machine %s left out: %s", tab, name, error.detail)
            unreachable.append(name)
    return {"ok": True, "tab": tab, "tickets": [*local, *elsewhere], "peer_unreachable": unreachable}


async def _may_write(tab: str, folder: Path) -> bool:
    """Whether the tab has read the place's boundary (= may add to the ticket kept there). A check that cannot run is no."""
    try:
        await ticket_checks.check_covers(tab, folder)
    except HTTPException:
        return False
    return True


async def _local(tab: str, ticket: str, row: ticket_index.IndexRow, since: str | None, today: date, now: datetime) -> dict:
    """One ticket kept on this machine. Its lines are judged for the tab only where the answer shows them: the first (the
    title) and the last a tab wrote (the next step). A place that cannot be found now leaves the ticket without a title."""
    entries: list[dict] = []
    title, step, writable = None, "", False
    try:
        folder = await ticket_places.folder_for(row.place_key)
        entries = await asyncio.to_thread(ticket_file.read, folder, ticket)
        latest = ticket_view.latest_tab_line(entries)
        wanted = entries[:1] + ([latest] if latest is not None and latest is not entries[0] else [])
        seen = {id(raw): shown for raw, shown in zip(wanted, await ticket_checks.filter_for_reader(tab, wanted))}
        title = seen[id(entries[0])].get("title") if entries else None
        step = ticket_view.first_line(seen[id(latest)].get("text")) if latest is not None else ""
        writable = await _may_write(tab, folder)
    except HTTPException as error:
        logger.info("ticket %s held by %s listed with what could be read: %s", ticket, tab, error.detail)
    return ticket_view.held_item(ticket, status=row.status, origin=row.origin, opener=row.opener, holder=tab, due=row.due,
                                 entries=entries, title=title if isinstance(title, str) else None, next_step=step,
                                 writable=writable, since=since, today=today, now=now)


async def _on_machine(home: Home, tab: str, since: str | None, today: date, now: datetime) -> list[dict]:
    """The tickets the tab holds that the other machine keeps (= outside every boundary, so the place is the one outside).
    The list names the holder as this machine reads it, a bare id for a tab here. Each ticket is read through `show`, which
    the other machine judges for this tab. Raises `HTTPException` when the machine does not answer."""
    reply = await call_peer(home.name, home.peer, TICKETS_PATH, timeout=PEER_LIST_TIMEOUT_SEC)
    listed = reply.body.get("tickets") if reply.status == 200 else None
    if not isinstance(listed, list):
        raise HTTPException(503, detail=f"{home.name} の機械が票の一覧を返しません")
    writable = await _may_write(tab, paths.TICKETS_DIR)
    items = []
    for row in listed:
        if not isinstance(row, dict) or row.get("holder") != tab or row.get("status") in (None, CLOSED) or not isinstance(row.get("id"), str):
            continue
        shown = (await ticket_relay.show(home, tab, row["id"])).get("entries")
        entries = shown if isinstance(shown, list) else []
        latest = ticket_view.latest_tab_line(entries)
        title = entries[0].get("title") if entries else None
        items.append(ticket_view.held_item(
            row["id"], status=row["status"], origin=row.get("origin") or ORIGIN_SELF, opener=str(row.get("opener", "")),
            holder=tab, due=row["due"] if isinstance(row.get("due"), str) else None, entries=entries,
            title=title if isinstance(title, str) else None,
            next_step=ticket_view.first_line(latest.get("text")) if latest is not None else "", writable=writable,
            since=since, today=today, now=now))
    return items
