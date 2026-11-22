"""Carry a ticket's command to the machine that keeps the ticket, from the machine whose tab typed it, and the calls the home
machine makes to the other machine for a `pass`. A ticket's home is the machine named at the head of its id. A command on a
ticket of another machine goes to that machine's backend through the doors under `/agent-messages/tickets` (`relay_home.py`
is the receiving end) and its answer comes back as it was. The command is never kept for later: a machine that does not
answer is `503 ticket_peer_down`, and the tab tries again when it is back (= a command kept would arrive at a ticket that
closed meanwhile, with nobody to tell it was refused). Called by `routes/tickets.py` and `ticket_pass.py`.
"""
from __future__ import annotations

import logging
import urllib.parse
from datetime import datetime, timezone
from typing import NamedTuple

from backend._common import config as _config
from backend._common.errors import raise_error
from backend._common.state import sessions_meta
from backend.peers import peer_health
from backend.peers.peer_call import PEER_LIST_TIMEOUT_SEC, PEER_TABS_PATH, TICKETS_PATH, PeerReply, call_peer
from backend.peers.peer_health_judgement import unreachable_message
from backend.routes.agent_messages import allowed_for_peer, judge, peer_refusal_message, split_peer
from backend.tickets import relay_judgement
from backend.tickets.relay_judgement import HERE

logger = logging.getLogger(__name__)


class Home(NamedTuple):
    """The other machine that keeps a ticket: its name in the configuration and its entry there."""

    name: str
    peer: dict


def home_of(ticket: str) -> Home | None:
    """The other machine a ticket is kept on, or None when it is kept on this one. `ticket_unknown` when the machine named
    in its id is neither this one nor one of the configured peers."""
    peers = _config.AGENT_MESSAGE_PEERS
    where = relay_judgement.home_of(ticket, _config.MACHINE_NAME, peers)
    if where is None:
        raise_error(404, "ticket_unknown", f"その id の票がありません: {ticket}", id=ticket)
    return None if where == HERE else Home(where, peers[where])


def _refusal_of(name: str, reply: PeerReply) -> None:
    """Give the other machine's refusal back to the tab as the HTTP error it was."""
    detail = reply.body.get("detail") if isinstance(reply.body.get("detail"), dict) else {}
    params = {key: value for key, value in (detail.get("params") or {}).items() if key not in ("status_code", "code", "message")}
    raise_error(reply.status if reply.status is not None and 400 <= reply.status < 600 else 502,
                detail.get("code") or "ticket_peer_failed",
                detail.get("message") or f"{name} の機械が理由を付けずに失敗を返しました (HTTP {reply.status})。 "
                "操作が済んでいるかもしれないので、 やり直す前に `tabs ticket show` で確かめてください",
                **{**params, "peer": name})


async def _carry(op: str, name: str, peer: dict, path: str, payload: dict | None, ticket: str) -> dict:
    """One call to the other machine. → its answer. `503 ticket_peer_down` when it does not answer (= nothing is kept; when the
    call was sent and only the answer is missing, the message says the command may have been done)."""
    reply = await call_peer(name, peer, path, payload)
    record = await peer_health.record_reply(name, peer, reply)
    if reply.status is None:
        logger.info("ticket relay: op=%s id=%s to=%s result=down", op, ticket, name)
        maybe = (" 操作は届いて済んでいるかもしれません。 やり直す前に `tabs ticket show` で確かめてください"
                 if reply.connected else "")
        raise_error(503, "ticket_peer_down",
                    f"{unreachable_message(name, record, datetime.now(timezone.utc))}。 票はその機械にあるので、 戻ってからやり直してください。{maybe}",
                    peer=name)
    if reply.status != 200:
        logger.info("ticket relay: op=%s id=%s to=%s result=refused http=%s", op, ticket, name, reply.status)
        _refusal_of(name, reply)
    logger.info("ticket relay: op=%s id=%s to=%s result=ok", op, ticket, name)
    return reply.body


def _may_talk_to(home: Home, sender: str) -> None:
    """The tab's account may talk to that machine (= the peer's `accounts`, as for a message)."""
    if not allowed_for_peer(home.peer, sender):
        raise_error(403, "agent_message_peer_not_allowed", peer_refusal_message(home.name, sender), peer=home.name)


async def _judged(home: Home, ticket: str, text: str) -> None:
    """Judge a text that leaves this machine for the ticket, as a message to `<machine>:<ticket id>` (= the way a message
    to a tab of another machine is judged)."""
    if text.strip() and _config.AGENT_MESSAGE_CHECK:
        name = f"{home.name}:{ticket}"
        await judge(name, text, name)


def _sender_fields(sender: str) -> dict:
    return {"from_session": sender, "from_title": sessions_meta[sender].title}


async def add(home: Home, sender: str, ticket: str, text: str, *, waiting: bool = False, due: str | None = None) -> dict:
    """`tabs ticket add` for a ticket kept on `home`, with `waiting` and `due` as the home machine reads them (= left out of the
    call when not given, so a home machine that does not know them still takes the line). → `{ok, id, status}` as it answers."""
    _may_talk_to(home, sender)
    await _judged(home, ticket, text)
    extra = {**({"waiting": True} if waiting else {}), **({"due": due} if due else {})}
    return await _carry("add", home.name, home.peer, f"{TICKETS_PATH}/{ticket}/entries",
                        {**_sender_fields(sender), "text": text, **extra}, ticket)


async def close(home: Home, sender: str, ticket: str, text: str) -> dict:
    """`tabs ticket close` for a ticket kept on `home`."""
    _may_talk_to(home, sender)
    await _judged(home, ticket, text)
    return await _carry("close", home.name, home.peer, f"{TICKETS_PATH}/{ticket}/close",
                        {**_sender_fields(sender), "text": text}, ticket)


async def show(home: Home, reader: str, ticket: str) -> dict:
    """`tabs ticket show` for a ticket kept on `home`: the home machine judges each line for this tab and gives no line of
    the operator's own words."""
    _may_talk_to(home, reader)
    return await _carry("show", home.name, home.peer, f"{TICKETS_PATH}/{ticket}?reader={urllib.parse.quote(reader, safe='')}", None, ticket)


async def pass_ticket(home: Home, sender: str, ticket: str, to: str) -> dict:
    """`tabs ticket pass` for a ticket kept on `home`: the home machine does it whoever the sender and the receiver are.
    The receiver is told as the tab spelled it (a bare name is a tab of this machine; `<machine>:<tab>` a tab of that one)."""
    _may_talk_to(home, sender)
    machine, tab = relay_judgement.destination_of(to, split_peer(to)[0], _config.MACHINE_NAME)
    return await _carry("pass", home.name, home.peer, f"{TICKETS_PATH}/{ticket}/pass",
                        {**_sender_fields(sender), "to_machine": machine, "to": tab}, ticket)


async def notify(name: str, peer: dict, *, ticket: str, to: str, from_machine: str, from_session: str, from_title: str) -> dict:
    """Ask the machine `name` to type the one line that tells the tab `to` (= an id or a name on that machine) a ticket was
    handed to it. → `{ok, to, kept?}`, `to` being the tab's id there."""
    return await _carry("notify", name, peer, f"{TICKETS_PATH}/{ticket}/notify",
                        {"to": to, "from_machine": from_machine, "from_session": from_session, "from_title": from_title},
                        ticket)


async def holder_listed(holder: str) -> bool | None:
    """Whether the other machine lists the tab `holder` (= `<machine>:<id>`) among its tabs: True or False when that machine
    answers (200) with its list, None when it does not or is not in the configuration (= the tab is taken to be there)."""
    name, _colon, tab = holder.partition(":")
    peer = _config.AGENT_MESSAGE_PEERS.get(name)
    if peer is None:
        return None
    reply = await call_peer(name, peer, PEER_TABS_PATH, timeout=PEER_LIST_TIMEOUT_SEC)
    tabs = reply.body.get("tabs")
    if reply.status != 200 or not isinstance(tabs, list):
        return None
    return any(isinstance(item, dict) and item.get("id") == tab for item in tabs)
