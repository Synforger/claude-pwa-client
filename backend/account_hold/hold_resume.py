"""Carries on the tabs the client owes a message to carry on, once they may run, and hands over the messages kept for
sleeping tabs. Three looks, in this order, each on the patrol's interval:

1. Stopped tabs whose account has a fallback (`resume_on_home`). Such a tab is stopped only while both that account and
   the account its fallback names are at their lines; once either is clear, a tab that had work left
   (`owes_carry_on`) is moved there (the fallback's own wake-up move) and sent the message the operator's "continue"
   sends, on the account it now runs on. A tab that had nothing left to do is only released: it is not moved, not
   woken, and sent nothing; the wake-up move takes it to a clear account whenever it is woken. A tab whose account has
   no fallback is continued by the operator only.
2. Awake tabs the client still owes a message (`carry_on_owed`): asked to come to a break and then neither moved nor
   stopped (the need went away), or a message that did not reach them. At a break on an account they may run on, they
   are sent the message once.
3. Kept messages (`hand_over_kept`): handed over in the order they came once the tab may run, or is awake.

Used by `hold_patrol.py`.
"""
from __future__ import annotations

import asyncio
import logging

from backend._common.state import save_sessions_meta, sessions_meta
from backend.account_fallback.fallback_patrol import move_before_wake
from backend.account_fallback.fallback_sensors import read_tab_break
from backend.account_hold.hold_continue import continue_tab, release_tab
from backend.account_hold.hold_mail import clear_account_for, may_run
from backend.account_hold.hold_settings import HoldRule
from backend.account_hold.hold_tabs import account_of
from backend.accounts.client_message import send_to_tab
from backend.accounts.tab_claim import claimed

logger = logging.getLogger(__name__)


async def _resume(session_id: str, rows: list[dict], hold_rules: dict[str, HoldRule], now: float) -> bool:
    """Carry one stopped tab on on the account that is clear for it. True when it was continued or released; False
    when it stays (the next look tries again)."""
    meta = sessions_meta.get(session_id)
    current = account_of(meta) if meta is not None else None
    if meta is None or meta.held_at is None or current is None:
        return False
    target = clear_account_for(meta, rows, hold_rules, now, for_messages=False)
    if target is None:
        return False
    if not meta.owes_carry_on:
        with claimed(session_id) as mine:
            if not mine:
                return False
            release_tab(meta)
        return True
    if current != target:
        await move_before_wake(session_id)
        if account_of(meta) != target:                       # the move was not made (the tab is busy, or it failed)
            return False
    if not await continue_tab(session_id, target):
        return False
    logger.info("account hold: resumed on %s session=%s from=%s", target, session_id, current)
    return True


async def resume_on_home(rows: list[dict], hold_rules: dict[str, HoldRule], now: float) -> list[str]:
    """Look at every stopped tab once. → the tabs that were continued or released."""
    held = [session_id for session_id, meta in list(sessions_meta.items()) if meta.held_at is not None]
    return [session_id for session_id in held if await _resume(session_id, rows, hold_rules, now)]


async def _carry_on(session_id: str, rows: list[dict], hold_rules: dict[str, HoldRule], now: float) -> bool:
    """Send one awake tab that is owed it the message to carry on. True when it took it."""
    meta = sessions_meta.get(session_id)
    current = account_of(meta) if meta is not None else None
    if (meta is None or current is None or not meta.owes_carry_on or meta.held_at is not None or meta.sleep is not None
            or meta.pause_asked_at is not None or meta.hold_asked_at is not None
            or not may_run(meta, rows, hold_rules, now)):
        return False
    tab_break = await asyncio.to_thread(read_tab_break, session_id)
    if not tab_break.at_break:
        return False
    if not await continue_tab(session_id, current, stopped=False):
        return False
    logger.info("account hold: carried on without a stop session=%s account=%s", session_id, current)
    return True


async def carry_on_owed(rows: list[dict], hold_rules: dict[str, HoldRule], now: float) -> list[str]:
    """Look at every awake tab the client owes a message to carry on. → the tabs that took it."""
    owed = [session_id for session_id, meta in list(sessions_meta.items()) if meta.owes_carry_on]
    return [session_id for session_id in owed if await _carry_on(session_id, rows, hold_rules, now)]


async def _hand_over(session_id: str, rows: list[dict], hold_rules: dict[str, HoldRule], now: float) -> int:
    """Hand the kept messages of one tab over, first come first. → how many it took; one that is not taken stays first
    and the next look tries again."""
    meta = sessions_meta.get(session_id)
    if meta is None or not meta.kept_messages:
        return 0
    if meta.sleep is not None and clear_account_for(meta, rows, hold_rules, now, for_messages=True) is None:
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
