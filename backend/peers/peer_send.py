"""Hands a message to another machine's backend, or keeps it when that machine does not answer.

A message gets an id when it is first handed over, and keeps it when it is sent again from the outbox, so that the other
machine delivers it once even when the first send did arrive and only the answer was lost (`seen_message_ids.py`). A
message is kept (answer `outbox: true`) when the machine could not be reached or gave no answer, and when messages kept
earlier for the same machine are still waiting (they go first, `outbox_flush.py`). A machine that answers and refuses
gives its refusal back to the sender; nothing is kept for that.

Used by `routes/agent_messages.py` after it has checked the message.
"""
from __future__ import annotations

import asyncio
import logging
import time
import uuid
from datetime import datetime, timezone

from backend._common.errors import raise_error
from backend.peers import outbox_flush, outbox_store, peer_health, peer_health_store
from backend.peers.peer_call import RELAYED_PATH, PeerReply, call_peer
from backend.peers.peer_health_judgement import EARLIER_WAITING, error_code, reason_of, unreachable_message

logger = logging.getLogger(__name__)

# The flushes started for a message queued behind earlier ones (= kept here so that they are not collected while running).
_flushes: set[asyncio.Task] = set()


def _earlier_waiting_message(name: str) -> str:
    return f"{name} の機械宛ての、 先に預かった連絡がまだ届いていません。 順に届けます"


def _outbox_answer(peer_name: str, tab: str, reason: str, message: str, record: dict | None) -> dict:
    return {"ok": True, "outbox": True, "to": f"{peer_name}:{tab}", "reason": reason, "message": message,
            "peer_state": record, "operator_said": False}


def _keep(entry: dict, record: dict | None, reason: str, message: str, *, maybe_delivered: bool = False) -> dict:
    """Write the message into the outbox and answer that it is kept. 502 with the code of the reason when it cannot be
    written (= it is not kept, and the sender is told it did not arrive)."""
    try:
        outbox_store.keep({**entry, "kept_at": time.time(), "tries": 0, "maybe_delivered": maybe_delivered})
    except OSError as error:
        logger.error("message to %s:%s could not be kept: %s", entry["peer"], entry["to"], error)
        raise_error(502, error_code(record), message, peer=entry["peer"])
    logger.info("message %s to %s:%s kept (%s)", entry["id"], entry["peer"], entry["to"], reason)
    return _outbox_answer(entry["peer"], entry["to"], reason, message, record)


async def send(peer_name: str, peer: dict, *, tab: str, sender: str, title: str, text: str) -> dict:
    """Hand a message from the tab `sender` (named `title`) to the tab `tab` of the machine `peer_name`. → the other
    machine's answer with `to` and `operator_said` added, or the outbox answer (`outbox: true`, why, the machine's
    record). The other machine's refusal is raised as the same HTTP error."""
    entry = {"id": uuid.uuid4().hex, "peer": peer_name, "to": tab, "from_session": sender, "from_title": title,
             "text": text}
    if outbox_store.pending(peer_name):
        record = peer_health_store.get(peer_name)
        if record is not None and record.get("ok"):
            task = asyncio.create_task(outbox_flush.flush_peer(peer_name))
            _flushes.add(task)
            task.add_done_callback(_flushes.discard)
            return _keep(entry, record, EARLIER_WAITING, _earlier_waiting_message(peer_name))
        return _keep(entry, record, reason_of(record), unreachable_message(peer_name, record, datetime.now(timezone.utc)))
    reply = await call_peer(peer_name, peer, RELAYED_PATH, {
        "to": tab, "from_title": title, "from_session": sender, "text": text, "message_id": entry["id"],
    })
    if reply.status is None:
        record = await peer_health.record_reply(peer_name, peer, reply)
        return _keep(entry, record, reason_of(record), unreachable_message(peer_name, record, datetime.now(timezone.utc)),
                     maybe_delivered=reply.connected)
    if reply.status != 200:
        _raise_refusal(peer_name, reply)
    await peer_health.record_reply(peer_name, peer, reply)
    return {**reply.body, "to": f"{peer_name}:{reply.body.get('to', tab)}", "operator_said": False}


def _raise_refusal(peer_name: str, reply: PeerReply) -> None:
    """Give the other machine's refusal back to the sender as the HTTP error it was."""
    detail = reply.body.get("detail") if isinstance(reply.body.get("detail"), dict) else {}
    params = {k: v for k, v in (detail.get("params") or {}).items() if k not in ("status_code", "code", "message")}
    raise_error(reply.status if 400 <= reply.status < 600 else 502, detail.get("code") or "agent_message_peer_failed",
                detail.get("message") or f"{peer_name} の機械が連絡を受け取りませんでした (HTTP {reply.status})",
                **{**params, "peer": peer_name})
