"""The account hold patrol: looks over the tabs on the rollover's interval and, while the usage of the 7 days of an
account is at its line of the day, stops the tabs that run on it (except the ones the operator pinned to their own
account) at a break. A stopped tab is put to sleep the way the sleep does it (`sleep/sleeper.py`: the same conversation
reopens when the tab is woken) and keeps the mark `held_at`; nothing continues it by itself, not even a day without a
line (see `docs/reference/account-hold.md`).

What is configured is in `hold_settings.py`, the judgement in `hold_judgement.py`; the break of a tab is read as the
account fallback reads it. A tab that keeps answering is asked once to come to a break (the mark is `hold_asked_at`);
when it does, the next look stops it. A message from another tab reaches a stopped tab as it does a sleeping one, and
wakes it: the patrol then takes the mark off.
"""
from __future__ import annotations

import asyncio
import logging
import time

from backend._common.state import SessionDef, save_sessions_meta, sessions_meta
from backend.account_fallback.fallback_judgement import pause_overdue
from backend.account_fallback.fallback_sensors import TabBreak, read_tab_break
from backend.account_fallback.fallback_settings import display_name_of
from backend.account_hold.hold_envelope import stop_envelope
from backend.account_hold.hold_judgement import is_over_line, should_ask_to_hold
from backend.account_hold.hold_settings import HoldRule, read_rules
from backend.account_hold.hold_tabs import account_of
from backend.accounts.client_message import send_to_tab
from backend.accounts.tab_claim import claimed
from backend.rollover.rollover import TICK_SEC
from backend.sleep.sleeper import sleep_at_break
from backend.usage.usage import read_all_rate_limits_tail

logger = logging.getLogger(__name__)

# The reasons a tab that is over the line was last left awake for, so that the same reasons are logged once.
_last_blocked: dict[str, tuple[str, ...]] = {}
# The tabs whose request to come to a break has been waited on for too long, so that it is said once.
_gave_up_on: set[str] = set()


def _clear_ask(session_id: str, meta: SessionDef) -> None:
    """Forget that the tab was asked to come to a break."""
    _gave_up_on.discard(session_id)
    _last_blocked.pop(session_id, None)
    if meta.hold_asked_at is not None:
        meta.hold_asked_at = None
        save_sessions_meta()


def _release_if_woken(session_id: str, meta: SessionDef) -> None:
    """Take the mark off a stopped tab that is awake again (= a message from another tab woke it): it is not stopped
    any more."""
    if meta.held_at is None or meta.sleep is not None:
        return
    meta.held_at = None
    save_sessions_meta()
    logger.info("account hold: released session=%s account=%s woken=1", session_id, account_of(meta))


async def _ask(session_id: str, meta: SessionDef, account: str, tab_break: TabBreak, now: float) -> None:
    """A tab that must be stopped but is not at a break: ask it once to come to one when it keeps answering, and say
    once that the request has gone unanswered for too long."""
    if meta.hold_asked_at is not None:
        if session_id not in _gave_up_on and pause_overdue(meta.hold_asked_at, now):
            _gave_up_on.add(session_id)
            logger.info("account hold: no break after asking to stop session=%s account=%s waited_sec=%d",
                        session_id, account, now - meta.hold_asked_at)
        return
    if not should_ask_to_hold(blocked_by=tab_break.blocked_by, stopped_by_limit=tab_break.stop is not None,
                              asked_at=meta.hold_asked_at):
        return
    meta.hold_asked_at = now
    save_sessions_meta()
    if not await send_to_tab(session_id, stop_envelope(account, display_name_of(account))):
        _clear_ask(session_id, meta)                                     # not delivered: the next look asks again
        return
    logger.info("account hold: asked to stop session=%s account=%s", session_id, account)


async def _hold(session_id: str, account: str, tab_break: TabBreak, now: float) -> bool:
    """Put the tab to sleep and mark it stopped. True when it slept; the tab that stays awake is looked at again."""
    reasons = await sleep_at_break(session_id, stopped_by_limit=tab_break.stop is not None)
    if reasons:
        logger.info("account hold: not now session=%s account=%s reasons=%s", session_id, account, ",".join(reasons))
        return False
    meta = sessions_meta.get(session_id)
    if meta is None:
        return False
    meta.held_at = now
    _clear_ask(session_id, meta)
    save_sessions_meta()
    logger.info("account hold: held session=%s account=%s stopped_by_limit=%s", session_id, account,
                tab_break.stop is not None)
    return True


async def _look(session_id: str, rows: list[dict], rules: dict[str, HoldRule], now: float) -> bool:
    """Look at one tab and stop it if it must. True when it was stopped."""
    meta = sessions_meta.get(session_id)
    if meta is None:
        return False
    _release_if_woken(session_id, meta)
    account = account_of(meta)
    over = is_over_line(rows, rules.get(account) if account else None, now)
    if over is not True or meta.account_pinned or meta.sleep is not None:
        _clear_ask(session_id, meta)                                     # under the line, kept where it is, or asleep
        return False
    with claimed(session_id) as mine:
        if not mine:
            return False
        tab_break = await asyncio.to_thread(read_tab_break, session_id)
        if _last_blocked.get(session_id) != tab_break.blocked_by:
            _last_blocked[session_id] = tab_break.blocked_by
            if tab_break.blocked_by:
                logger.info("account hold: waits session=%s account=%s reasons=%s", session_id, account,
                            ",".join(tab_break.blocked_by))
        if tab_break.at_break:
            return await _hold(session_id, account, tab_break, now)
        await _ask(session_id, meta, account, tab_break, now)
        return False


async def tick() -> list[str]:
    """Look over every tab once. → the tabs that were stopped."""
    rules = read_rules()
    if not rules and not any(meta.held_at is not None or meta.hold_asked_at is not None
                             for meta in sessions_meta.values()):
        return []
    rows = await asyncio.to_thread(read_all_rate_limits_tail)
    now = time.time()
    return [session_id for session_id in list(sessions_meta) if await _look(session_id, rows, rules, now)]


async def hold_loop(interval_sec: float = TICK_SEC) -> None:
    """Look over the tabs every `interval_sec` (= the rollover's interval)."""
    logger.info("hold_loop started (interval=%ds)", interval_sec)
    try:
        while True:
            await asyncio.sleep(interval_sec)
            try:
                await tick()
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("hold_loop iteration failed")
    except asyncio.CancelledError:
        logger.info("hold_loop cancelled")
        raise
