"""The child watch patrol: looks over the child tabs on the rollover's interval and, for a child that stopped without
reporting, sends its parent one message. See `docs/reference/child-sessions.md`.

A child that waits at a permission window for `window_state.PERMISSION_WAIT_SEC` is told the same way, once per window
(its mark is the time the window opened), with the reason `permission`: its turn is open, so no look at a break finds it.

The judgement is `watch_judgement.py`. A stop is told once: the time of the child's last row is kept in the child's
definition before the message is sent, so neither a later look nor a restart of the backend sends it again. A child
that works on and stops again has a new last row, and so is a new stop.
"""
from __future__ import annotations

import asyncio
import logging
import time

from backend._common.state import SessionDef, save_sessions_meta, sessions_meta
from backend.accounts.client_message import send_to_tab
from backend.accounts.tab_claim import claimed
from backend.child_watch.watch_envelope import child_stopped_envelope
from backend.child_watch.watch_judgement import PERMISSION, permission_overdue, should_tell
from backend.child_watch.watch_sensors import is_watching, look_at_child
from backend.permission_window import window_state
from backend.rollover.rollover import TICK_SEC

logger = logging.getLogger(__name__)

# The last row time of each child seen at a break on its previous look. Memory only: after a restart of the backend a
# stopped child needs two looks again.
_seen_at_break: dict[str, float] = {}


async def _send_or_keep(parent_id: str, text: str) -> bool:
    """Send the parent the message, or keep it for the parent while it sleeps with no account clear to run on
    (`account_hold.hold_mail`), so that the notice does not wake it on an account at its line. True when it was sent
    or kept."""
    # Imported here: the account hold imports the account fallback, which sends its messages through the message
    # route, which imports this package.
    from backend.account_hold import hold_mail  # noqa: PLC0415
    if await asyncio.to_thread(hold_mail.must_keep, parent_id):
        hold_mail.keep(parent_id, text)
        return True
    return await send_to_tab(parent_id, text)


async def _look(session_id: str) -> bool:
    """Look at one tab and tell its parent if it stopped without reporting. True when the message was sent."""
    meta = sessions_meta.get(session_id)
    look = None
    if meta is not None and await asyncio.to_thread(is_watching, meta):
        opened_at = window_state.permission_opened_at(session_id)
        if opened_at is not None and permission_overdue(opened_at=opened_at, now=time.time(),
                                                        wait_sec=window_state.PERMISSION_WAIT_SEC):
            # Its turn is open, so it is not at a break and is looked at no further: the window is what it waits at.
            _seen_at_break.pop(session_id, None)
            return meta.parent_id is not None and await tell_parent(meta, opened_at, PERMISSION)
        look = await asyncio.to_thread(look_at_child, meta)
    previous = _seen_at_break.pop(session_id, None)
    if look is None or meta is None or meta.parent_id is None:
        return False
    _seen_at_break[session_id] = look.mark
    if not should_tell(mark=look.mark, previous=previous, told=meta.stop_told_at):
        return False
    return await tell_parent(meta, look.mark, look.reason)


async def tell_parent(meta: SessionDef, mark: float, reason: str) -> bool:
    """Tell the parent of the child `meta` that it stopped at the stop whose last row is at `mark`, for `reason`, unless
    that stop was told already. True when the message was sent or kept for the parent. The error resume tells a parent
    through this too, so that the watch does not tell the same stop again."""
    if meta.parent_id is None or meta.stop_told_at == mark:
        return False
    with claimed(meta.parent_id) as mine:
        if not mine:
            return False
        before, meta.stop_told_at = meta.stop_told_at, mark     # before sending: a restart must not send it twice
        save_sessions_meta()
        sent = await _send_or_keep(meta.parent_id, child_stopped_envelope(meta.id, meta.title, reason))
        if not sent:
            meta.stop_told_at = before                          # nothing arrived; the next look tries again
            save_sessions_meta()
        logger.info("child watch: session=%s parent=%s reason=%s sent=%s", meta.id, meta.parent_id, reason, sent)
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
