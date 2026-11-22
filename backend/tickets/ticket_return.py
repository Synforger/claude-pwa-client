"""Give a ticket back when the tab that holds it is gone. Every `RETURN_PATROL_SEC`, and before an answer is delivered, a
ticket that is not closed is looked at: when its holder is not a tab any more, it goes back to the tab that asked first (which
is told in one line), and when that tab is gone too, it is held by nobody (= the operator's screen chooses the tab to give it
to). A holder on the other machine is looked up in that machine's list of tabs, and given up only when the machine answers
and the tab is not on it. The judgement is `answer_judgement.return_step`; called by `answer_delivery.py` and started from
`backend/main.py`.
"""
from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable

from fastapi import HTTPException

from backend._common.errors import raise_error
from backend._common.state import sessions_meta
from backend._internal.stop_signal import BackendStopping
from backend.routes.agent_messages import deliver_or_keep, hand_over_work
from backend.tickets import (answer_judgement, ticket_entry, ticket_index, ticket_notify, ticket_places, ticket_relay,
                             ticket_service, ticket_view)
from backend.tickets.answer_judgement import CLEAR_HOLDER, RETURN_TO_OPENER, HolderFacts
from backend.tickets.return_envelope import returned_envelope
from backend.tickets.ticket_index import CLOSED, IndexRow

logger = logging.getLogger(__name__)

#: How often the holders of the open tickets are looked at
RETURN_PATROL_SEC = 60.0


async def _facts_of(row: IndexRow) -> HolderFacts:
    """What is known of the holder: for a tab of this machine its own table, for a tab of the other machine that machine's
    list of tabs (asked only for such a holder)."""
    remote = ":" in row.holder
    listed = await ticket_relay.holder_listed(row.holder) if remote else None
    return HolderFacts(holder=row.holder, holder_is_remote=remote, holder_here=row.holder in sessions_meta,
                       opener_here=row.opener in sessions_meta, holder_listed=listed)


def _still_held_by(holder: str) -> Callable[[IndexRow], None]:
    """A check for `ticket_service.write_entry`: the change is made only while `holder` still holds the ticket (= a ticket
    handed over in the meantime is not taken back)."""
    def check(row: IndexRow) -> None:
        if row.holder != holder:
            raise_error(409, "ticket_holder_changed", "票の持ち主が、 戻す間に替わりました")
    return check


async def _tell_opener(ticket: str, opener: str) -> bool:
    """Tell the tab the ticket is its own again. → False when it could not be told (= the ticket is not moved, and the
    next look tries again)."""
    try:
        await deliver_or_keep(opener, returned_envelope(ticket))
    except HTTPException as error:
        logger.warning("ticket returned: id=%s to=%s could not be told: %s", ticket, opener, error.detail)
        return False
    return True


async def _hand_work_to_child(tab_id: str) -> None:
    """The opener may be a child tab that reported: it holds work again, so its memo says working (= as it does when its
    parent sends it a message)."""
    meta = sessions_meta.get(tab_id)
    if meta is not None and meta.child and meta.parent_id:
        await hand_over_work(meta.parent_id, tab_id)


async def return_if_gone(ticket: str) -> bool:
    """Look at the holder of the ticket and, when it is gone, give the ticket back. The opener is told first, so that a tab
    that cannot be reached leaves the ticket as it was. → True when the holder changed."""
    row = ticket_index.get(ticket)
    if row is None or row.status == CLOSED:
        return False
    step = answer_judgement.return_step(await _facts_of(row))
    if step == answer_judgement.STAY:
        return False
    target = row.opener if step == RETURN_TO_OPENER else ""
    folder = await ticket_places.folder_for(row.place_key)
    if step == RETURN_TO_OPENER and not await _tell_opener(ticket, target):
        return False
    entry = ticket_entry.make_entry(ticket_entry.RETURNED, ticket_entry.CLIENT_WRITER, "", at=ticket_service.now(),
                                    to=target, **{"from": row.holder})
    try:
        await asyncio.to_thread(ticket_service.write_entry, ticket, folder, entry, {"holder": target},
                                check=_still_held_by(row.holder))
    except HTTPException as error:
        logger.info("ticket returned: id=%s was not moved: %s", ticket, error.detail)
        return False
    logger.info("ticket returned: id=%s from=%s to=%s", ticket, row.holder, target)
    if step == RETURN_TO_OPENER:
        await _hand_work_to_child(target)
    elif step == CLEAR_HOLDER:
        logger.warning("ticket returned: id=%s has no tab to go back to (holder and opener are both closed)", ticket)
        ticket_notify.schedule(ticket, ticket_view.ATTENTION_NO_HOLDER)
    return True


async def tick() -> list[str]:
    """Look at every ticket once. → the tickets whose holder changed."""
    returned = []
    for ticket, row in list(ticket_index.rows().items()):
        if row.status == CLOSED:
            continue
        try:
            if await return_if_gone(ticket):
                returned.append(ticket)
        except HTTPException as error:
            logger.info("ticket returned: id=%s was not looked at: %s", ticket, error.detail)
    return returned


async def return_loop(interval_sec: float = RETURN_PATROL_SEC) -> None:
    """Look over the tickets every `interval_sec`."""
    logger.info("ticket return loop started (interval=%ds)", interval_sec)
    try:
        while True:
            await asyncio.sleep(interval_sec)
            try:
                await tick()
            except asyncio.CancelledError:
                raise
            except BackendStopping:
                logger.info("ticket return loop: the backend is stopping; this look was left")
            except Exception:
                logger.exception("ticket return loop iteration failed")
    except asyncio.CancelledError:
        logger.info("ticket return loop cancelled")
        raise
