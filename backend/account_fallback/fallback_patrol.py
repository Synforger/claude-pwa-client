"""The account fallback patrol: looks over the tabs on the rollover's interval, moves the tabs of an account whose
usage is at its line to the account its fallback names, and brings them back when the usage is over.

What is configured is in `fallback_settings.py`, the judgement in `fallback_judgement.py`, what is read about a tab in
`fallback_sensors.py`; the move itself is `accounts/account_move.py` (see `docs/reference/account-fallback.md`). A
tab asleep is not moved (that would wake it): `move_before_wake` moves it when it is woken. A tab whose turn the
limit stopped is moved at once, with the tool results of that turn, and told to carry on.
"""
from __future__ import annotations

import asyncio
import logging
import time

from fastapi import HTTPException

from backend._common.config import default_account_id
from backend._common.state import sessions_meta
from backend.account_fallback.fallback_envelope import carry_on_envelope
from backend.account_fallback.fallback_judgement import Move, decide, home_is_limited
from backend.account_fallback.fallback_sensors import TabBreak, read_tab_break, sleeping_stop
from backend.account_fallback.fallback_settings import FallbackRule, read_rules
from backend.accounts.account_move import move_tab_account
from backend.accounts.client_message import send_to_tab
from backend.accounts.tab_claim import claimed
from backend.fork.lineage import LineageCut
from backend.rollover.rollover import TICK_SEC
from backend.usage.usage import read_all_rate_limits_tail

logger = logging.getLogger(__name__)

# The reasons a tab that is wanted elsewhere was last held for, so that the same reasons are logged once.
_last_blocked: dict[str, tuple[str, ...]] = {}


def _accounts_of(session_id: str) -> tuple[str, str] | None:
    """(the account the tab runs on, the account it belongs to), None for a tab that is not in the list."""
    meta = sessions_meta.get(session_id)
    if meta is None:
        return None
    current = meta.account_id or default_account_id() or ""
    return current, meta.fallback_from or current


def _limited(rows: list[dict], rule: FallbackRule | None, now: float) -> bool | None:
    return home_is_limited(rows, rule, now) if rule is not None else None


async def _move(session_id: str, current: str, home: str, rule: FallbackRule | None, action: Move,
                tab_break: TabBreak) -> bool:
    """Do `action` on the tab. True when it moved. A move that fails leaves the tab on the account it was on, and the
    next look tries again."""
    moving = action is Move.MOVE
    target = rule.to_account if moving and rule is not None else home
    cut = LineageCut.THROUGH_TOOL_RESULTS if tab_break.stop is not None else LineageCut.CLEAN_TURN
    try:
        await move_tab_account(session_id, target, cut=cut, fallback_from=home if moving else None)
    except HTTPException as error:
        logger.warning("account fallback: could not move session=%s from=%s to=%s: %s", session_id, current, target,
                       error.detail)
        return False
    logger.info("account fallback: %s session=%s from=%s to=%s stopped_by_limit=%s",
                "moved" if moving else "returned", session_id, current, target, tab_break.stop is not None)
    if tab_break.stop is not None:
        await send_to_tab(session_id, carry_on_envelope(current, target))
    return True


async def _look(session_id: str, rows: list[dict], now: float) -> bool:
    """Look at one tab and move it if it must. True when it moved."""
    accounts = _accounts_of(session_id)
    meta = sessions_meta.get(session_id)
    if accounts is None or meta is None or meta.sleep is not None:
        return False
    current, home = accounts
    rule = read_rules().get(home)
    limited = _limited(rows, rule, now)
    wanted = decide(current=current, home=home, rule=rule, limited=limited, at_break=True, pinned=meta.account_pinned)
    if wanted is Move.STAY:
        _last_blocked.pop(session_id, None)
        return False
    with claimed(session_id) as mine:
        if not mine:
            return False
        tab_break = await asyncio.to_thread(read_tab_break, session_id)
        action = decide(current=current, home=home, rule=rule, limited=limited, at_break=tab_break.at_break,
                        pinned=meta.account_pinned)
        if _last_blocked.get(session_id) != tab_break.blocked_by:
            _last_blocked[session_id] = tab_break.blocked_by
            if tab_break.blocked_by:
                logger.info("account fallback: waits session=%s account=%s reasons=%s", session_id, current,
                            ",".join(tab_break.blocked_by))
        if action is Move.STAY:
            return False
        return await _move(session_id, current, home, rule, action, tab_break)


async def tick() -> list[str]:
    """Look over every tab once. → the tabs that were moved or brought back."""
    if not read_rules() and not any(meta.fallback_from for meta in sessions_meta.values()):
        return []
    rows = await asyncio.to_thread(read_all_rate_limits_tail)
    now = time.time()
    return [session_id for session_id in list(sessions_meta) if await _look(session_id, rows, now)]


async def move_before_wake(session_id: str) -> None:
    """Called before a sleeping tab is reopened: when the account it belongs to is at its line, the tab is moved to the
    account its fallback names and wakes there. It is asleep, so it is at a break by definition."""
    accounts = _accounts_of(session_id)
    if accounts is None:
        return
    current, home = accounts
    rule = read_rules().get(home)
    if rule is None:
        return
    rows = await asyncio.to_thread(read_all_rate_limits_tail)
    limited = _limited(rows, rule, time.time())
    wanted = decide(current=current, home=home, rule=rule, limited=limited, at_break=True,
                    pinned=sessions_meta[session_id].account_pinned)
    if wanted is not Move.MOVE:
        return
    with claimed(session_id) as mine:
        if not mine:
            return
        stop = await asyncio.to_thread(sleeping_stop, session_id)
        cut = LineageCut.THROUGH_TOOL_RESULTS if stop is not None else LineageCut.CLEAN_TURN
        try:
            await move_tab_account(session_id, rule.to_account, cut=cut, fallback_from=home)
        except HTTPException as error:
            logger.warning("account fallback: a sleeping tab stays on its account session=%s: %s", session_id,
                           error.detail)
            return
        logger.info("account fallback: moved session=%s from=%s to=%s asleep=1", session_id, current, rule.to_account)


async def fallback_loop(interval_sec: float = TICK_SEC) -> None:
    """Look over the tabs every `interval_sec` (= the rollover's interval)."""
    logger.info("fallback_loop started (interval=%ds)", interval_sec)
    try:
        while True:
            await asyncio.sleep(interval_sec)
            try:
                await tick()
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("fallback_loop iteration failed")
    except asyncio.CancelledError:
        logger.info("fallback_loop cancelled")
        raise
