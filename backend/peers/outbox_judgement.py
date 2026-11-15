"""What to do with a kept message, given what the other machine answered when it was sent again: no file, no network.

Used by `outbox_flush.py`.
"""
from __future__ import annotations

from backend.peers.peer_call import PeerReply

# How long a message is kept for a machine that does not come back (= then it is dropped, and its sender is told).
EXPIRY_SEC = 72 * 3600
# What a send again came to.
DELIVERED = "delivered"          # the other machine took it (or had it already)
REFUSED = "refused"              # the other machine answered that it will never take it: delete it
NOT_REACHED = "not_reached"      # no answer: the machine is down again, so nothing else is sent to it now
TRY_LATER = "try_later"          # it answered that it cannot take it now: keep it
# Only these answers are final. 409 (the tab is not ready, the same message is in flight) and 5xx pass with time.
_REFUSAL_STATUSES = (400, 403, 404)
UNKNOWN_RECEIVER = "agent_message_unknown_receiver"


def verdict(reply: PeerReply) -> str:
    """What a send again of a kept message came to."""
    if reply.status is None:
        return NOT_REACHED
    if reply.status == 200:
        return DELIVERED
    return REFUSED if reply.status in _REFUSAL_STATUSES else TRY_LATER


def is_expired(entry: dict, now: float) -> bool:
    """Whether a kept message was kept longer than `EXPIRY_SEC`."""
    return now - entry.get("kept_at", now) > EXPIRY_SEC


def refusal_of(reply: PeerReply) -> tuple[str, str]:
    """The code and the words with which the other machine refused a message."""
    detail = reply.body.get("detail") if isinstance(reply.body.get("detail"), dict) else {}
    return detail.get("code") or f"http_{reply.status}", detail.get("message") or f"HTTP {reply.status}"
