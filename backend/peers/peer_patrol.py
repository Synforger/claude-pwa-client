"""The watch over the other machines (`agent_message_peers`): on an interval it asks each one for its tab list, writes down
whether it answered (`peer_health.py`), sends the messages kept for one that answers (`outbox_flush.py`) and drops the
kept messages that waited too long. Started with the backend; with no machine configured it only does the last.

`CPC_PEER_CHECK_INTERVAL_SEC` shortens the interval for tests of the whole path.
"""
from __future__ import annotations

import asyncio
import logging
import os

from backend.peers import outbox_flush, peer_health
from backend.peers.peer_call import PEER_LIST_TIMEOUT_SEC, PEER_TABS_PATH, call_peer

logger = logging.getLogger(__name__)

# How often each machine is looked at (= a machine that went to sleep is known within this).
CHECK_INTERVAL_SEC = 300.0
# How long after the backend starts the first look is made (= not while it is still starting).
STARTUP_DELAY_SEC = 5.0


def _interval_sec() -> float:
    try:
        return float(os.environ.get("CPC_PEER_CHECK_INTERVAL_SEC", CHECK_INTERVAL_SEC))
    except ValueError:
        return CHECK_INTERVAL_SEC


async def check_peer(name: str, peer: dict) -> None:
    """Look at one machine once: write down whether it answered, and send what is kept for it when it does."""
    reply = await call_peer(name, peer, PEER_TABS_PATH, timeout=PEER_LIST_TIMEOUT_SEC)
    record = await peer_health.record_reply(name, peer, reply)
    logger.info("peer %s ok=%s since=%s error=%s tailnet=%s", name, record["ok"], record["since"], record["last_error"],
                record["tailnet"])
    if record["ok"]:
        await outbox_flush.flush_peer(name)


async def tick() -> None:
    """Look over every machine once (= all at the same time, so a slow one does not hold up the others), and drop the
    kept messages that waited too long."""
    from backend._common.config import AGENT_MESSAGE_PEERS  # noqa: PLC0415
    await outbox_flush.expire_old()
    looked = await asyncio.gather(*(check_peer(name, peer) for name, peer in AGENT_MESSAGE_PEERS.items()),
                                  return_exceptions=True)
    for name, outcome in zip(AGENT_MESSAGE_PEERS, looked):
        if isinstance(outcome, BaseException):
            logger.error("peer %s: the look failed", name, exc_info=outcome)


async def peer_loop(interval_sec: float | None = None) -> None:
    """Look over the other machines every `interval_sec` (= `CHECK_INTERVAL_SEC`), the first time shortly after the start."""
    interval_sec = _interval_sec() if interval_sec is None else interval_sec
    logger.info("peer_loop started (interval=%ds)", interval_sec)
    try:
        await asyncio.sleep(STARTUP_DELAY_SEC)
        while True:
            try:
                await tick()
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("peer_loop iteration failed")
            await asyncio.sleep(interval_sec)
    except asyncio.CancelledError:
        logger.info("peer_loop cancelled")
        raise
