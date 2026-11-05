"""The child watch patrol: looks over the child tabs on the rollover's interval and, for a child that stopped without
reporting, sends its parent one message. See `docs/reference/child-sessions.md`.

The judgement is `watch_judgement.py`. A stop is told once: the time of the child's last row is kept in the child's
definition before the message is sent, so neither a later look nor a restart of the backend sends it again. A child
that works on and stops again has a new last row, and so is a new stop.
"""
from __future__ import annotations

import asyncio
import logging

from backend._common.state import save_sessions_meta, sessions_meta
from backend.accounts.client_message import send_to_tab
from backend.accounts.tab_claim import claimed
from backend.child_watch.watch_envelope import child_stopped_envelope
from backend.child_watch.watch_judgement import should_tell
from backend.child_watch.watch_sensors import is_watching, look_at_child
from backend.rollover.rollover import TICK_SEC

logger = logging.getLogger(__name__)

# The last row time of each child seen at a break on its previous look. Memory only: after a restart of the backend a
# stopped child needs two looks again.
_seen_at_break: dict[str, float] = {}


async def _look(session_id: str) -> bool:
    """Look at one tab and tell its parent if it stopped without reporting. True when the message was sent."""
    meta = sessions_meta.get(session_id)
    look = None
    if meta is not None and await asyncio.to_thread(is_watching, meta):
        look = await asyncio.to_thread(look_at_child, meta)
    previous = _seen_at_break.pop(session_id, None)
    if look is None or meta is None or meta.parent_id is None:
        return False
    _seen_at_break[session_id] = look.mark
    if not should_tell(mark=look.mark, previous=previous, told=meta.stop_told_at):
        return False
    with claimed(meta.parent_id) as mine:
        if not mine:
            return False
        before, meta.stop_told_at = meta.stop_told_at, look.mark     # before sending: a restart must not send it twice
        save_sessions_meta()
        sent = await send_to_tab(meta.parent_id, child_stopped_envelope(session_id, meta.title, look.reason))
        if not sent:
            meta.stop_told_at = before                              # nothing arrived; the next look tries again
            save_sessions_meta()
        logger.info("child watch: session=%s parent=%s reason=%s sent=%s", session_id, meta.parent_id, look.reason, sent)
        return sent


async def tick() -> list[str]:
    """Look over every tab once. → the children whose parent was told."""
    for gone in set(_seen_at_break) - set(sessions_meta):
        del _seen_at_break[gone]
    return [session_id for session_id in list(sessions_meta) if await _look(session_id)]


async def watch_loop(interval_sec: float = TICK_SEC) -> None:
    """Look over the tabs every `interval_sec` (= the rollover's interval)."""
    logger.info("watch_loop started (interval=%ds)", interval_sec)
    try:
        while True:
            await asyncio.sleep(interval_sec)
            try:
                await tick()
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("watch_loop iteration failed")
    except asyncio.CancelledError:
        logger.info("watch_loop cancelled")
        raise
