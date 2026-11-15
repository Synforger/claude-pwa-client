"""Sends the kept messages again once a machine answers, and drops those that waited too long.

One flush runs per machine at a time (a lock each), oldest message first. A message that arrived (or was already taken:
the other machine knows its id) or was refused for good (400, 403, 404) is deleted and its sender told. Any other answer
(409, 5xx) keeps it, and the messages after it for the same tab wait for it; a machine that does not answer again stops
the flush. A message new for a machine whose outbox is not empty is added to the outbox (`peer_send.py`) and goes out
through the same flush, so messages reach a tab in the order they were sent.

Used by `peer_patrol.py` (when a machine answers) and `peer_send.py` (a message queued behind earlier ones).
"""
from __future__ import annotations

import asyncio
import logging
import time

from backend.peers import outbox_judgement, outbox_notice, outbox_store, peer_health
from backend.peers.outbox_notify import notify_sender
from backend.peers.peer_call import RELAYED_PATH, call_peer

logger = logging.getLogger(__name__)

# The lock of each machine's flush.
_locks: dict[str, asyncio.Lock] = {}


def _payload(entry: dict) -> dict:
    return {"to": entry["to"], "from_title": entry["from_title"], "from_session": entry["from_session"],
            "text": entry["text"], "message_id": entry["id"]}


async def flush_peer(name: str) -> None:
    """Send the messages kept for the machine `name` again, oldest first, until one cannot go or none is left. Does nothing
    when a flush of this machine is running (= it picks up what was added)."""
    from backend._common.config import AGENT_MESSAGE_PEERS  # noqa: PLC0415
    peer = AGENT_MESSAGE_PEERS.get(name)
    lock = _locks.setdefault(name, asyncio.Lock())
    if peer is None or lock.locked():
        return
    async with lock:
        waiting_tabs: set[str] = set()
        tried: set[str] = set()
        while True:
            entry = next((e for e in outbox_store.pending(name)
                          if e["id"] not in tried and e["to"] not in waiting_tabs), None)
            if entry is None:
                return
            tried.add(entry["id"])
            if not await _send_again(name, peer, entry, waiting_tabs):
                return


async def _send_again(name: str, peer: dict, entry: dict, waiting_tabs: set[str]) -> bool:
    """Send one kept message again. False when the machine did not answer (= stop the flush)."""
    reply = await call_peer(name, peer, RELAYED_PATH, _payload(entry))
    verdict = outbox_judgement.verdict(reply)
    if verdict == outbox_judgement.DELIVERED:
        outbox_store.remove(entry["id"])
        await peer_health.record_reply(name, peer, reply)
        await notify_sender(entry, outbox_notice.notice_envelope(outbox_notice.DELIVERED, entry))
        logger.info("kept message %s delivered to %s:%s duplicate=%s tries=%d", entry["id"], name, entry["to"],
                    bool(reply.body.get("duplicate")), entry.get("tries", 0) + 1)
    elif verdict == outbox_judgement.REFUSED:
        code, message = outbox_judgement.refusal_of(reply)
        outbox_store.remove(entry["id"])
        await notify_sender(entry, outbox_notice.notice_envelope(outbox_notice.REFUSED, entry, message, code))
        logger.info("kept message %s refused by %s:%s (%s), dropped", entry["id"], name, entry["to"], code)
    elif verdict == outbox_judgement.NOT_REACHED:
        outbox_store.count_try(entry)
        await peer_health.record_reply(name, peer, reply)
        return False
    else:
        outbox_store.count_try(entry)
        waiting_tabs.add(entry["to"])
        logger.info("kept message %s not taken by %s:%s yet (HTTP %s), kept", entry["id"], name, entry["to"], reply.status)
    return True


async def expire_old(now: float | None = None) -> None:
    """Drop every kept message that has waited longer than `outbox_judgement.EXPIRY_SEC`, and tell its sender."""
    now = time.time() if now is None else now
    for entry in outbox_store.pending():
        if outbox_judgement.is_expired(entry, now):
            outbox_store.remove(entry["id"])
            await notify_sender(entry, outbox_notice.notice_envelope(outbox_notice.EXPIRED, entry))
            logger.info("kept message %s for %s:%s dropped after %d tries: it waited too long", entry["id"],
                        entry["peer"], entry["to"], entry.get("tries", 0))
