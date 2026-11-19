"""The picture of the tickets the screen is given on the `tickets` channel of the unified stream: this machine's tickets (=
`ticket_service.list_tickets`, which the operator reads whole) and what the other machines have waiting for the operator. A
screen is given one when it connects and one every time something changed (`ticket_wake.py`). Called by
`routes/unified_stream.py`.
"""
from __future__ import annotations

from backend.tickets import ticket_peer_count, ticket_service


async def snapshot() -> dict:
    """`{"tickets": [...], "peers": {<machine>: {"waiting": N} | {"unreadable": true}}}`."""
    listed = await ticket_service.list_tickets()
    return {"tickets": listed["tickets"], "peers": ticket_peer_count.counts()}
