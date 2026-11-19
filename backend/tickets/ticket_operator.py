"""What the operator's screen does with one ticket besides answering it (`ticket_answer.py`): read it whole, hand a ticket no
tab holds to a tab, and say it looked at an answer that did not arrive. The operator reads everything, so nothing is judged
by the guard. The doors are `routes/tickets.py`, and they sit under the path the guard blocks for the tabs
(`/tickets/*/answer*`). See `docs/reference/tickets.md`.
"""
from __future__ import annotations

import asyncio

from backend._common.errors import raise_error
from backend.tickets import ticket_entry, ticket_file, ticket_pass, ticket_places, ticket_service, ticket_view


async def read(ticket: str) -> dict:
    """The ticket as the operator reads it: every line by time with the operator's own words and the client's lines in them,
    and the row's fields with what the screen draws its lower part from (`answer_pending`, `last_delivery`, `attention`).
    → `{ok, id, status, wants, holder, opener, place_outside, entries, answer_pending, last_delivery, attention}`."""
    row = ticket_service.row_of(ticket)
    folder = await ticket_places.folder_for(row.place_key)
    entries = await asyncio.to_thread(ticket_file.read, folder, ticket)
    delivery = ticket_view.last_delivery(entries)
    return {"ok": True, "id": ticket, "status": row.status, "wants": row.wants, "holder": row.holder, "opener": row.opener,
            "place_outside": row.place_key == ticket_places.outside_key(), "entries": entries,
            "answer_pending": ticket_view.answer_pending(entries), "last_delivery": delivery,
            "attention": ticket_view.attention(row.status, row.holder, delivery)}


async def hand_to(ticket: str, to: str) -> dict:
    """Hand a ticket that no tab holds to the tab `to` (= its id), as the operator. `ticket_has_holder` when a tab holds it:
    the operator picks a holder only for a ticket that has none. The tab is told first and must have read the place's
    boundary (`ticket_pass.hand_over`). An answer on its way goes to the new holder. → `{ok, id, to, kept?}`."""
    row = ticket_service.row_of(ticket, open_only=True)
    if row.holder:
        raise_error(409, "ticket_has_holder", f"その票は、 もうタブが持っています。 渡し直せません: {ticket}", id=ticket)
    return await ticket_pass.hand_over(ticket, ticket_pass.OPERATOR_PARTY, ticket_pass.Party(None, to), by_operator=True)


async def seen(ticket: str) -> dict:
    """The operator looked at the last answer that did not arrive (or may not have): add the `seen` line, which takes the
    ticket out of the ones that want a look. A closed ticket takes it too. Nothing is added when there is nothing to look at
    (= `written` is false: the screen was old, or another screen looked first). → `{ok, id, written}`."""
    row = ticket_service.row_of(ticket)
    folder = await ticket_places.folder_for(row.place_key)
    entries = await asyncio.to_thread(ticket_file.read, folder, ticket)
    delivery = ticket_view.last_delivery(entries)
    if delivery is None or delivery["result"] not in ("refused", "unconfirmed") or delivery["followed"]:
        return {"ok": True, "id": ticket, "written": False}
    entry = ticket_entry.make_entry(ticket_entry.SEEN, ticket_entry.CLIENT_WRITER, "", at=ticket_service.now())
    await asyncio.to_thread(ticket_service.record, ticket, folder, entry)
    return {"ok": True, "id": ticket, "written": True}
