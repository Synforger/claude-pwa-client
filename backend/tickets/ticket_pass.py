"""Hand a ticket to another tab: the holder moves to it, a `passed` line is added, and the tab is told in one line through
the way messages between tabs go (= a tab with no Claude is started, a tab the account hold stopped has it kept). The
line says only that the ticket is its now: the tab reads the request in the ticket, which nobody has rewritten on the way.
Called by `routes/tickets.py`.
"""
from __future__ import annotations

import asyncio
import logging

from backend._common.errors import raise_error
from backend.routes.agent_messages import (
    OPENING,
    NOT_SENT_CODE,
    NOT_SENT_MESSAGE,
    check,
    deliver_or_keep,
    envelope,
    failing_as,
    hand_over_work,
    resolve_receiver,
    sender_title,
    split_peer,
    tab_reachable,
)
from backend.tickets import answer_queue, ticket_checks, ticket_entry, ticket_places, ticket_service
from backend.tickets.ticket_index import WAITING_OPERATOR

logger = logging.getLogger(__name__)


def notice_text(ticket: str) -> str:
    """The one line a tab gets when a ticket is handed to it."""
    return f"票 {ticket} を渡されました。 `tabs ticket show {ticket}` で読んでください"


def notice_envelope(sender: str, title: str, ticket: str) -> str:
    """The envelope of the line: the one of a message between tabs, with the ticket's id as one more attribute of its
    tag (= the first line, which says who wrote it, is the same as for any message). The id is checked to be safe to
    write there, and the tag's other fields cannot hold a quote."""
    opening, tag, body = envelope(sender, notice_text(ticket), None, title).split("\n", 2)
    if opening != OPENING or not tag.endswith('">'):
        raise ValueError("the envelope of a message has changed its form")
    return f'{opening}\n{tag[:-1]} ticket="{ticket}">\n{body}'


def _refuse_while_answer_is_coming(ticket: str) -> None:
    """The operator's answer is on its way to the tab that holds the ticket: the ticket stays with it until it arrives
    (= only the return of a ticket whose holder is gone changes who holds it, `ticket_return.py`)."""
    if answer_queue.pending_for(ticket):
        raise_error(409, "ticket_answer_pending", f"その票への操作者の答えが、 まだ持ち主に届いていません。 届いてから渡してください: {ticket}",
                    id=ticket)


async def pass_ticket(sender: str, ticket: str, to: str) -> dict:
    """Hand `ticket` from the tab `sender` to the tab `to` (= its id or name).

    The ticket must be open, not waiting for the operator and with no answer of the operator's still to reach its holder,
    and both tabs must have read the place's boundary.
    A tab on another machine is not taken yet (`ticket_peer_not_yet`). The tab is told first and the ticket changes
    after, so a tab that cannot be reached leaves the ticket as it was.
    → `{"ok", "id", "to", "kept"?}`."""
    peer, _tab = split_peer(to)
    if peer is not None:
        raise_error(501, "ticket_peer_not_yet", "別の機械のタブへは、 まだ票を渡せません", to=to)
    with failing_as(NOT_SENT_CODE, NOT_SENT_MESSAGE):
        receiver = resolve_receiver(to)
        if receiver == sender:
            raise_error(400, "ticket_to_self", "自分のタブへは票を渡せません")
    row = ticket_service.row_of(ticket, open_only=True)
    if row.status == WAITING_OPERATOR:
        raise_error(409, "ticket_waiting_operator", f"その票は操作者の返事を待っています。 渡せません: {ticket}", id=ticket)
    _refuse_while_answer_is_coming(ticket)
    folder = await ticket_places.folder_for(row.place_key)
    await ticket_checks.check_covers(sender, folder)
    await ticket_checks.check_covers(receiver, folder)
    with failing_as(NOT_SENT_CODE, NOT_SENT_MESSAGE):
        if not tab_reachable(receiver):
            raise_error(409, "agent_message_receiver_not_running", "宛先のタブで claude が動いておらず、 起動できません")
        await check(receiver, notice_text(ticket))
        message = notice_envelope(sender, await sender_title(sender, receiver), ticket)
    result = await deliver_or_keep(receiver, message)
    entry = ticket_entry.make_entry(ticket_entry.PASSED, ticket_service.writer_of(sender), "", at=ticket_service.now(),
                                    to=receiver)
    await asyncio.to_thread(ticket_service.write_entry, ticket, folder, entry, {"holder": receiver}, must_be_open=True,
                            check=lambda _row: _refuse_while_answer_is_coming(ticket))
    logger.info("ticket %s passed from=%s to=%s ok=%s kept=%s", ticket, sender, receiver, result.get("ok"),
                result.get("kept", False))
    await hand_over_work(sender, receiver)
    answer = {"ok": True, "id": ticket, "to": receiver}
    return {**answer, "kept": True} if result.get("kept") else answer
