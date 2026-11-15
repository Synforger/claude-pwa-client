"""Writes down whether another machine answered: after a look of the watch and after a message was handed over. A
machine that does not answer is also looked up on the tailnet, to tell a machine that is off (asleep, no power, no
network) from a backend that is not running.

Used by `peer_patrol.py`, `peer_send.py` and `outbox_flush.py`.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone

from backend.peers import peer_health_store, tailnet_peers
from backend.peers.peer_call import PeerReply
from backend.peers.peer_health_judgement import next_record

# What `last_error` says when the other backend did not answer at all (= the request could not be sent / was sent and no
# answer came); an answer that is not 200 is `http_<status>`.
UNREACHABLE = "unreachable"
NO_ANSWER = "no_answer"
_OK = 200


def _error_of(reply: PeerReply) -> str | None:
    if reply.status == _OK:
        return None
    if reply.status is not None:
        return f"http_{reply.status}"
    return NO_ANSWER if reply.connected else UNREACHABLE


async def record_reply(name: str, peer: dict, reply: PeerReply) -> dict:
    """Write down what `reply` (a call to the machine `name`) says: it answers when the status is 200. When it does not,
    the tailnet is asked about it too. → the record."""
    error = _error_of(reply)
    ok = error is None
    tailnet = {"online": None, "last_seen": None}
    if not ok:
        tailnet = await asyncio.to_thread(tailnet_peers.peer_status, peer["address"])
    now = datetime.now(timezone.utc)
    return peer_health_store.update(
        name, lambda previous: next_record(previous, ok=ok, error=error, tailnet=tailnet, now=now))
