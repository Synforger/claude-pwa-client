"""Hand a ticket to another tab: the holder moves to it, a `passed` line is added, and the tab is told in one line through
the way messages between tabs go (= a tab with no Claude is started, a tab the account hold stopped has it kept). The
line says only that the ticket is its now: the tab reads the request in the ticket, which nobody has rewritten on the way.

The machine that keeps the ticket does it, whichever machine the tab that passes it and the tab that takes it are on
(`hand_over`): it makes the checks, has the tab told (typed here, or by the other machine when the tab is there: its name is
turned into an id on the machine it lives on) and writes the line and the holder after the tab was told, so that a tab that
cannot be reached leaves the ticket as it was. Called by `routes/tickets.py` and `relay_home.py`.
"""
from __future__ import annotations

import asyncio
import logging
from typing import NamedTuple

from backend._common import config as _config
from backend._common.errors import raise_error
from backend.routes.agent_messages import (
    OPENING,
    NOT_SENT_CODE,
    NOT_SENT_MESSAGE,
    allowed_for_peer,
    check,
    deliver_or_keep,
    envelope,
    failing_as,
    hand_over_work,
    judge,
    relayed_envelope,
    resolve_receiver,
    sender_title,
    split_peer,
    tab_reachable,
)
from backend.tickets import (answer_queue, relay_judgement, ticket_checks, ticket_entry, ticket_places, ticket_relay,
                             ticket_service, ticket_state)
from backend.tickets.ticket_index import WAITING_OPERATOR

logger = logging.getLogger(__name__)


class Party(NamedTuple):
    """A tab that gives or takes a ticket. `machine` is None for a tab of this machine and the other machine's name for a
    tab of that one; `tab` is the tab's id (the one that gives) or its id or name (the one that takes) on its own machine;
    `title` is the name of the one that gives."""

    machine: str | None
    tab: str
    title: str = ""


#: The name a tab sees as the sender of the line when the operator hands it a ticket from the screen
OPERATOR_NAME = "operator"
#: Who hands a ticket when the operator does it from the screen (= no tab; the client writes the `passed` line)
OPERATOR_PARTY = Party(None, "", OPERATOR_NAME)


def notice_text(ticket: str, *, by_operator: bool = False) -> str:
    """The one line a tab gets when a ticket is handed to it (= by another tab, or by the operator from the screen)."""
    who = "操作者から" if by_operator else ""
    return f"票 {ticket} を{who}渡されました。 `tabs ticket show {ticket}` で読んでください"


def _with_ticket(message: str, ticket: str) -> str:
    """The envelope with the ticket's id as one more attribute of its tag (= the first line, which says who wrote it, is the
    one of any message). The id is checked to be safe to write there, and the tag's other fields cannot hold a quote."""
    opening, tag, body = message.split("\n", 2)
    if not tag.endswith('">'):
        raise ValueError("the envelope of a message has changed its form")
    return f'{opening}\n{tag[:-1]} ticket="{ticket}">\n{body}'


def notice_envelope(sender: str, title: str, ticket: str, *, by_operator: bool = False) -> str:
    """The envelope of the line for a tab of this machine, from a tab of this machine (`sender` is empty and `title` the
    operator's name when the operator hands it from the screen)."""
    message = envelope(sender, notice_text(ticket, by_operator=by_operator), None, title)
    if message.split("\n", 1)[0] != OPENING:
        raise ValueError("the envelope of a message has changed its form")
    return _with_ticket(message, ticket)


def relayed_notice_envelope(machine: str, title: str, session: str, ticket: str) -> str:
    """The envelope of the line for a tab of this machine, from a tab of the machine `machine` (= the first line says it came
    from another machine, as for any message from there)."""
    return _with_ticket(relayed_envelope(machine, title, session, notice_text(ticket)), ticket)


def _refuse_while_answer_is_coming(ticket: str) -> None:
    """The operator's answer is on its way to the tab that holds the ticket: the ticket stays with it until it arrives
    (= only the return of a ticket whose holder is gone changes who holds it, `ticket_return.py`)."""
    if answer_queue.pending_for(ticket):
        raise_error(409, "ticket_answer_pending", f"その票への操作者の答えが、 まだ持ち主に届いていません。 届いてから渡してください: {ticket}",
                    id=ticket)


async def pass_ticket(sender: str, ticket: str, to: str) -> dict:
    """Hand `ticket`, kept on this machine, from the tab `sender` of this machine to the tab `to` (= its id or name; with
    `<machine>:` in front, a tab of that machine).

    The ticket must be open, not waiting for the operator and with no answer of the operator's still to reach its holder,
    and a tab of this machine must have read the place's boundary. The tab is told first and the ticket changes after.
    → `{"ok", "id", "to", "kept"?}`."""
    peer, _tab = split_peer(to)
    machine, tab = relay_judgement.destination_of(to, peer, _config.MACHINE_NAME)
    return await hand_over(ticket, Party(None, sender, ticket_service.writer_of(sender).tab_title),
                           Party(None if peer is None else machine, tab))


async def pass_from_peer(peer_name: str, session: str, title: str, ticket: str, to_machine: str, to: str) -> dict:
    """The tab `session` (named `title`) of the other machine `peer_name` passes `ticket`, kept here, to `to` on the machine
    `to_machine` (= this one, or that one; a third is refused). → what `hand_over` answers, with the tab named as the other
    machine reads it."""
    named = relay_judgement.machine_of_party(to_machine, _config.MACHINE_NAME, peer_name)
    if named == relay_judgement.THIRD:
        raise_error(409, "ticket_to_third_machine", "票は、 この 2 台の機械のタブへだけ渡せます", to=to_machine)
    answer = await hand_over(ticket, Party(peer_name, session, title), Party(named, to))
    return {**answer, "to": relay_judgement.seen_from(answer["to"], _config.MACHINE_NAME, peer_name)}


async def hand_over(ticket: str, sender: Party, receiver: Party, *, by_operator: bool = False) -> dict:
    """Hand `ticket` from `sender` to `receiver` (= either may be on the other machine). The ticket must be kept outside
    every boundary when either is (`ticket_inside_boundary`): what is judged for a tab that has read no boundary is all that
    crosses. `by_operator` is the operator handing a ticket no tab holds, from the screen (`ticket_operator.py`): `sender` is
    `OPERATOR_PARTY` (a tab of this machine with no id), the client writes the line, and a ticket that waits for the operator,
    or whose answer is still on its way, is let through (= it is the way such a ticket gets a holder; the answer goes to the
    new one). The receiver still must have read the place's boundary, and is still told before anything is written.
    → `{"ok", "id", "to", "kept"?}`, `to` being the holder as the index writes it."""
    if sender.machine == receiver.machine and receiver.tab == sender.tab:
        raise_error(400, "ticket_to_self", "自分のタブへは票を渡せません")
    receiver_id = None
    if receiver.machine is None:
        with failing_as(NOT_SENT_CODE, NOT_SENT_MESSAGE):
            receiver_id = resolve_receiver(receiver.tab)
            if sender.machine is None and receiver_id == sender.tab:
                raise_error(400, "ticket_to_self", "自分のタブへは票を渡せません")
    row = ticket_service.row_of(ticket, open_only=True)
    if row.status == WAITING_OPERATOR and not by_operator:
        raise_error(409, "ticket_waiting_operator", f"その票は操作者の返事を待っています。 渡せません: {ticket}", id=ticket)
    if not by_operator:
        _refuse_while_answer_is_coming(ticket)
    if (sender.machine or receiver.machine) is not None and row.place_key != ticket_places.outside_key():
        raise_error(403, "ticket_inside_boundary", "その票は境界の中にあり、 別の機械のタブへは渡せません", id=ticket)
    folder = await ticket_places.folder_for(row.place_key)
    if sender.machine is None and not by_operator:
        await ticket_checks.check_covers(sender.tab, folder)
    if receiver_id is not None:
        await ticket_checks.check_covers(receiver_id, folder)
    holder, kept = await _tell(ticket, sender, receiver, receiver_id, by_operator=by_operator)
    if by_operator:
        writer = ticket_entry.CLIENT_WRITER
    elif sender.machine is None:
        writer = ticket_service.writer_of(sender.tab)
    else:
        writer = ticket_entry.Writer(*relay_judgement.writer_name(sender.machine, sender.tab, sender.title), "")
    entry = ticket_entry.make_entry(ticket_entry.PASSED, writer, "", at=ticket_service.now(), to=holder)
    await asyncio.to_thread(ticket_service.write_entry, ticket, folder, entry, ticket_state.after_pass(holder),
                            must_be_open=not by_operator,
                            check=None if by_operator else (lambda _row: _refuse_while_answer_is_coming(ticket)))
    logger.info("ticket %s passed from=%s to=%s kept=%s", ticket, relay_judgement.tab_of(sender.machine, sender.tab), holder, kept)
    if sender.machine is None and receiver_id is not None and not by_operator:
        await hand_over_work(sender.tab, receiver_id)
    answer = {"ok": True, "id": ticket, "to": holder}
    return {**answer, "kept": True} if kept else answer


async def _tell(ticket: str, sender: Party, receiver: Party, receiver_id: str | None, *,
                by_operator: bool = False) -> tuple[str, bool]:
    """Have the receiver told in one line. → (the holder as the index writes it, whether the line was kept for a tab the
    account hold stopped). Nothing is changed by this: a failure leaves the ticket as it was."""
    if receiver_id is not None:
        with failing_as(NOT_SENT_CODE, NOT_SENT_MESSAGE):
            if not tab_reachable(receiver_id):
                raise_error(409, "agent_message_receiver_not_running", "宛先のタブで claude が動いておらず、 起動できません")
            await check(receiver_id, notice_text(ticket, by_operator=by_operator))
            if by_operator:
                message = notice_envelope("", OPERATOR_NAME, ticket, by_operator=True)
            elif sender.machine is None:
                message = notice_envelope(sender.tab, await sender_title(sender.tab, receiver_id), ticket)
            else:
                message = relayed_notice_envelope(sender.machine, sender.title, sender.tab, ticket)
        result = await deliver_or_keep(receiver_id, message)
        return receiver_id, bool(result.get("kept"))
    peer = _config.AGENT_MESSAGE_PEERS[receiver.machine]
    if sender.machine is None:
        if not allowed_for_peer(peer, sender.tab):
            raise_error(403, "agent_message_peer_not_allowed", f"このタブは {receiver.machine} の機械と連絡できません",
                        peer=receiver.machine)
    if _config.AGENT_MESSAGE_CHECK:
        name = f"{receiver.machine}:{receiver.tab}"
        await judge(name, notice_text(ticket), name)
    sent_from = _config.MACHINE_NAME if sender.machine is None else sender.machine
    answer = await ticket_relay.notify(receiver.machine, peer, ticket=ticket, to=receiver.tab, from_machine=sent_from,
                                       from_session=sender.tab, from_title=sender.title)
    return relay_judgement.tab_of(receiver.machine, str(answer["to"])), bool(answer.get("kept"))
