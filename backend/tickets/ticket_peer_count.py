"""How many tickets the other machine has waiting for the operator, read from its list of tickets every `INTERVAL_SEC`
(= the screen shows it as one line: the operator answers those on that machine's screen). The other machine gives only the
tickets kept outside every boundary (`relay_home.list_tickets`), so the count says so. Called by `backend/main.py`
(`count_loop`) and `ticket_feed.py` (`counts`).
"""
from __future__ import annotations

import asyncio
import logging

from backend._common import config as _config
from backend.peers.peer_call import PEER_LIST_TIMEOUT_SEC, TICKETS_PATH, call_peer
from backend.tickets import ticket_view, ticket_wake

logger = logging.getLogger(__name__)

#: How often each machine's list is read
INTERVAL_SEC = 60.0
#: How long after the backend starts the first look is made (= not while it is still starting)
STARTUP_DELAY_SEC = 5.0

#: Machine name → its waiting count, or None when it did not give a list. A machine not looked at yet has no entry.
_counts: dict[str, int | None] = {}


def counts() -> dict[str, dict]:
    """What the screen is given: each machine looked at, with `{"waiting": N}` or `{"unreadable": True}`."""
    return {name: ({"waiting": count} if count is not None else {"unreadable": True}) for name, count in _counts.items()
            if name in _config.AGENT_MESSAGE_PEERS}


async def look_once() -> None:
    """Read every machine's list once (= all at the same time) and wake the screens when a count changed."""
    peers = dict(_config.AGENT_MESSAGE_PEERS)
    replies = await asyncio.gather(*(call_peer(name, peer, TICKETS_PATH, timeout=PEER_LIST_TIMEOUT_SEC)
                                     for name, peer in peers.items()))
    changed = False
    for name, reply in zip(peers, replies):
        count = ticket_view.waiting_count(reply.body) if reply.status == 200 else None
        if name not in _counts or _counts[name] != count:
            _counts[name] = count
            changed = True
            logger.info("ticket peer count: machine=%s waiting=%s", name, "unreadable" if count is None else count)
    if changed:
        ticket_wake.wake()


async def count_loop(interval_sec: float = INTERVAL_SEC) -> None:
    """Read the other machines' lists every `interval_sec`, the first time shortly after the start."""
    logger.info("ticket peer count started (interval=%ds)", interval_sec)
    try:
        await asyncio.sleep(STARTUP_DELAY_SEC)
        while True:
            try:
                await look_once()
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("ticket peer count iteration failed")
            await asyncio.sleep(interval_sec)
    except asyncio.CancelledError:
        logger.info("ticket peer count cancelled")
        raise
