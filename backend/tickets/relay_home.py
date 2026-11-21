"""The receiving end of a ticket's commands on the machine that keeps the ticket (= its home), called by the other machine's
backend through the doors under `/agent-messages/tickets` (`routes/tickets.py`; `ticket_relay.py` is the sending end).

Only a ticket kept outside every boundary is given to the other machine, whatever the command: its lines were judged for a
reader that has read nothing, and a ticket inside a boundary never leaves the machine that has the boundary
(`403 ticket_inside_boundary`). A line the other machine's tab adds is written as `<machine>:<tab>` / `<title> @<machine>`
with no tier, and judged as the addition of a reader that has read no boundary. A line of the operator's own words is not
given: the other machine reads its kind and time only. Tabs are named as the other machine reads them (`seen_from`).
"""
from __future__ import annotations

import asyncio
import logging

from backend._common import config as _config
from backend._common import paths
from backend._common.errors import raise_error
from backend.routes.agent_messages import (
    NOT_SENT_CODE,
    NOT_SENT_MESSAGE,
    allowed_for_peer,
    check,
    deliver_or_keep,
    failing_as,
    resolve_receiver,
    tab_reachable,
)
from backend.tickets import (relay_judgement, ticket_checks, ticket_entry, ticket_file, ticket_index, ticket_places,
                             ticket_service, ticket_state)
from backend.tickets.ticket_entry import Writer
from backend.tickets.ticket_pass import notice_text, relayed_notice_envelope
from backend.tickets.ticket_index import CLOSED, IndexRow

logger = logging.getLogger(__name__)

#: The fields of a line that name a tab (= written as the other machine reads them)
_TAB_FIELDS = ("tab", "to", "from")


def _given_row(ticket: str, *, open_only: bool = False) -> IndexRow:
    """The ticket's row when it may be given to the other machine (= kept outside every boundary)."""
    row = ticket_service.row_of(ticket, open_only=open_only)
    if row.place_key != ticket_places.outside_key():
        raise_error(403, "ticket_inside_boundary", "その票は境界の中にあり、 別の機械の操作は受けません", id=ticket)
    return row


def _writer(peer_name: str, session: str, title: str) -> Writer:
    tab, tab_title = relay_judgement.writer_name(peer_name, session, title)
    return Writer(tab, tab_title, "")


async def add(peer_name: str, ticket: str, session: str, title: str, text: str, *, waiting: bool = False,
              due: str | None = None) -> dict:
    """The other machine's tab `session` (named `title`) adds `text` to the ticket, which `waiting` sets aside and `due` gives a
    day (`ticket_state.after_add`, as for a tab here). The text is judged as the addition of a reader that has read no
    boundary. → `{ok, id, status}`."""
    row = _given_row(ticket, open_only=True)
    folder = await ticket_places.folder_for(row.place_key)
    await ticket_checks.check_write(folder, text)
    extra = {**({"waiting": True} if waiting else {}), **({"due": due} if due else {})}
    entry = ticket_entry.make_entry(ticket_entry.ADDED, _writer(peer_name, session, title), text, at=ticket_service.now(), **extra)
    row = await asyncio.to_thread(ticket_service.write_entry, ticket, folder, entry,
                                  ticket_state.after_add(waiting=waiting, due=due))
    logger.info("ticket relayed in: op=add id=%s from=%s:%s", ticket, peer_name, session)
    return {"ok": True, "id": ticket, "status": row.status}


async def close(peer_name: str, ticket: str, session: str, title: str, text: str) -> dict:
    """The other machine's tab closes the ticket, with a last word when there is one. → `{ok, id, status}`."""
    row = _given_row(ticket, open_only=True)
    folder = await ticket_places.folder_for(row.place_key)
    if text.strip():
        await ticket_checks.check_write(folder, text)
    entry = ticket_entry.make_entry(ticket_entry.CLOSED, _writer(peer_name, session, title), text, at=ticket_service.now())
    row = await asyncio.to_thread(ticket_service.write_entry, ticket, folder, entry, {"status": CLOSED, "wants": None})
    logger.info("ticket relayed in: op=close id=%s from=%s:%s", ticket, peer_name, session)
    return {"ok": True, "id": ticket, "status": row.status}


def _entry_seen_from(entry: dict, peer_name: str) -> dict:
    """The line with the tabs it names written as the other machine reads them."""
    own = _config.MACHINE_NAME
    return {key: (relay_judgement.seen_from(value, own, peer_name) if key in _TAB_FIELDS and isinstance(value, str) else value)
            for key, value in entry.items()}


async def show(peer_name: str, ticket: str, reader: str) -> dict:
    """The ticket as the other machine's tab `reader` may read it: each line judged as a message to that tab (= a tab of
    another machine has read nothing here), the operator's own words withheld. → what `tabs ticket show` prints, as the
    other machine reads it."""
    row = _given_row(ticket)
    folder = await ticket_places.folder_for(row.place_key)
    entries = await asyncio.to_thread(ticket_file.read, folder, ticket)
    given = [ticket_entry.withheld(entry) if entry.get("kind") in relay_judgement.OPERATOR_KINDS else entry for entry in entries]
    judged = await ticket_checks.filter_for_session(f"{peer_name}:{reader}", given)
    own = _config.MACHINE_NAME
    logger.info("ticket relayed in: op=show id=%s from=%s:%s", ticket, peer_name, reader)
    return {"ok": True, "id": ticket, "status": row.status, "wants": row.wants, "home": own,
            "holder": relay_judgement.seen_from(row.holder, own, peer_name),
            "opener": relay_judgement.seen_from(row.opener, own, peer_name), "place_outside": True,
            "entries": [_entry_seen_from(entry, peer_name) for entry in judged]}


async def list_tickets(peer_name: str) -> dict:
    """The tickets kept outside every boundary, for the other machine's screen and its tabs' lists: their id, state, who holds and
    asked first, when they were opened, where they came from (`origin`) and their due day. No title (= a title is content, and the lines are read through `show`); a ticket inside a boundary
    is not named at all."""
    own = _config.MACHINE_NAME
    tickets = []
    for ticket, row in ticket_index.rows().items():
        if row.place_key != ticket_places.outside_key():
            continue
        first = next(iter(await asyncio.to_thread(ticket_file.read, paths.TICKETS_DIR, ticket)), {})
        tickets.append({"id": ticket, "opened_at": first.get("at"), "status": row.status, "wants": row.wants,
                        "holder": relay_judgement.seen_from(row.holder, own, peer_name),
                        "opener": relay_judgement.seen_from(row.opener, own, peer_name), "origin": row.origin, "due": row.due})
    logger.info("ticket relayed in: op=list id=- from=%s", peer_name)
    return {"ok": True, "home": own, "tickets": sorted(tickets, key=lambda item: (item["opened_at"] or "", item["id"]), reverse=True)}



async def notify(peer_name: str, peer: dict, ticket: str, to: str, from_machine: str, from_session: str, from_title: str) -> dict:
    """Type the one line that tells the tab `to` (= its id or name on this machine) that `ticket`, kept on the other machine,
    was handed to it. The tab that handed it is on `from_machine`, which is this machine or the one that calls (= any other is
    refused). The name is turned into an id here, where the tab lives, and the line goes through this machine's own check
    like any message from the other machine. → `{ok, to, kept?}`, `to` being the tab's id."""
    if relay_judgement.machine_of_party(from_machine, _config.MACHINE_NAME, peer_name) == relay_judgement.THIRD:
        raise_error(409, "ticket_to_third_machine", "票は、 この 2 台の機械のタブからだけ渡せます", to=from_machine)
    with failing_as(NOT_SENT_CODE, NOT_SENT_MESSAGE):
        receiver = resolve_receiver(to)
        if not allowed_for_peer(peer, receiver):
            raise_error(403, "agent_message_peer_not_allowed", f"宛先のタブは {peer_name} の機械と連絡できません", peer=peer_name)
        if not tab_reachable(receiver):
            raise_error(409, "agent_message_receiver_not_running", "宛先のタブで claude が動いておらず、 起動できません")
        await check(receiver, notice_text(ticket))
        message = relayed_notice_envelope(from_machine, from_title, from_session, ticket)
    result = await deliver_or_keep(receiver, message)
    logger.info("ticket relayed in: op=notify id=%s from=%s:%s", ticket, from_machine, from_session)
    answer = {"ok": True, "to": receiver}
    return {**answer, "kept": True} if result.get("kept") else answer
