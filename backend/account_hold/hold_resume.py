"""Resumes the tabs the account hold stopped whose account has a fallback, on whichever account is clear first, and
hands over the messages kept for stopped tabs once they may take them.

A tab whose account has a fallback is stopped only while both that account and the account its fallback names are at
their lines. When the account it belongs to drops below its line, the tab is brought back to it; when the account the
fallback names drops below its hold line first, the tab is moved there (the fallback's own move, which a message from
another tab starts too). Then it is sent the message the operator's "continue" sends (`hold_continue.continue_tab`), on
the account it now runs on. An account at its line is never used: the tab leaves it before it carries on. While both
are still at their lines, or the usage is not known, nothing changes and the tab stays stopped for the operator to
continue. A tab whose account has no fallback is continued by the operator only.

The messages from other tabs that `hold_mail.py` kept for a stopped tab are handed over, in the order they came, once
the tab may take them: it has been continued or woken, or an account is clear for it.

Used by `hold_patrol.py`.
"""
from __future__ import annotations

import logging

from backend._common.state import save_sessions_meta, sessions_meta
from backend.account_fallback.fallback_patrol import move_before_wake
from backend.account_hold.hold_continue import continue_tab
from backend.account_hold.hold_mail import clear_account_for
from backend.account_hold.hold_settings import HoldRule
from backend.account_hold.hold_tabs import account_of
from backend.accounts.client_message import send_to_tab

logger = logging.getLogger(__name__)


async def _resume(session_id: str, rows: list[dict], hold_rules: dict[str, HoldRule], now: float) -> bool:
    """Move one stopped tab to the account that is clear for it and continue it there. True when it carries on; False
    when it stays (the next look tries again)."""
    meta = sessions_meta.get(session_id)
    current = account_of(meta) if meta is not None else None
    if meta is None or meta.held_at is None or current is None:
        return False
    target = clear_account_for(meta, rows, hold_rules, now, for_messages=False)
    if target is None:
        return False
    if current != target:
        await move_before_wake(session_id)
        if account_of(meta) != target:                       # the move was not made (the tab is busy, or it failed)
            return False
    if not await continue_tab(session_id, target):
        return False
    logger.info("account hold: resumed on %s session=%s from=%s", target, session_id, current)
    return True


async def resume_on_home(rows: list[dict], hold_rules: dict[str, HoldRule], now: float) -> list[str]:
    """Look at every stopped tab once. → the tabs that were moved to an account clear for them and continued."""
    held = [session_id for session_id, meta in list(sessions_meta.items()) if meta.held_at is not None]
    return [session_id for session_id in held if await _resume(session_id, rows, hold_rules, now)]


async def _hand_over(session_id: str, rows: list[dict], hold_rules: dict[str, HoldRule], now: float) -> int:
    """Hand the kept messages of one tab over, first come first. → how many it took; one that is not taken stays first
    and the next look tries again."""
    meta = sessions_meta.get(session_id)
    if meta is None or not meta.kept_messages:
        return 0
    stopped = meta.held_at is not None and meta.sleep is not None
    if stopped and clear_account_for(meta, rows, hold_rules, now, for_messages=True) is None:
        return 0
    taken = 0
    while meta.kept_messages:
        if not await send_to_tab(session_id, meta.kept_messages[0]):
            break
        meta.kept_messages.pop(0)
        save_sessions_meta()
        taken += 1
    logger.info("account hold: handed over kept messages session=%s taken=%d left=%d", session_id, taken,
                len(meta.kept_messages))
    return taken


async def hand_over_kept(rows: list[dict], hold_rules: dict[str, HoldRule], now: float) -> list[str]:
    """Look at every tab with kept messages once. → the tabs that took at least one."""
    kept = [session_id for session_id, meta in list(sessions_meta.items()) if meta.kept_messages]
    return [session_id for session_id in kept if await _hand_over(session_id, rows, hold_rules, now)]
