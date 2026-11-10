"""The account fallback patrol: looks over the tabs on the rollover's interval, moves the tabs of an account whose
usage is at its line to the account its fallback names (the tabs whose cache is cold already `ahead_pct` before the
line), and brings them back when the usage is over (the tabs whose cache is cold, once the account is clear of that
width; at once when the account they run on has reached its own line and theirs has not).

What is configured is in `fallback_settings.py`, the judgement in `fallback_judgement.py`, what is read about a tab in
`fallback_sensors.py`; the move itself is `accounts/account_move.py` (see `docs/reference/account-fallback.md`). A
tab asleep is not moved (that would wake it): `move_before_wake` moves it, or brings it back, when it is woken. A tab
whose turn the limit stopped is moved at once, with the tool results of that turn, and told to carry on. A tab that
keeps answering is asked once to come to a break (the mark is `pause_asked_at`) when it must move whatever its cache
is; when it does, the same look moves it and tells it to carry on. No tab is moved to an account at its hold line, so
the carry-on always lands on an account clear of its lines; with both accounts at their lines the tab is not asked to
pause either, and the account hold stops it where it is (`account_hold/`).
"""
from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass

from fastapi import HTTPException

from backend._common.config import default_account_id
from backend._common.state import SessionDef, save_sessions_meta, sessions_meta
from backend.account_fallback.fallback_envelope import (
    LIMIT, PAUSE, carry_on_envelope, pause_envelope, return_pause_envelope)
from backend.account_fallback.fallback_judgement import (
    Move, cold_reasons, decide, home_is_limited, home_is_near, pause_overdue, returns_over_target_line,
    should_ask_to_pause, urgent_move)
from backend.account_fallback.fallback_sensors import TabBreak, read_tab_break, sleeping_stop
from backend.account_fallback.fallback_settings import FallbackRule, display_name_of, read_rules
from backend.accounts.account_move import move_tab_account
from backend.accounts.client_message import send_to_tab
from backend.accounts.tab_claim import claimed
from backend.fork.lineage import LineageCut
from backend.rollover.rollover import TICK_SEC
from backend.usage.usage import read_all_rate_limits_tail

logger = logging.getLogger(__name__)

# The reasons a tab that is wanted elsewhere was last held for, so that the same reasons are logged once.
_last_blocked: dict[str, tuple[str, ...]] = {}
# The tabs whose request to come to a break has been waited on for too long, so that it is said once.
_gave_up_on: set[str] = set()
# What was last said about a tab that stays on purpose (= it waits for its cache to go cold, or for the account it
# would move to to be under its line), so that the same thing is said once.
_last_note: dict[str, str] = {}


def _accounts_of(session_id: str) -> tuple[str, str] | None:
    """(the account the tab runs on, the account it belongs to), None for a tab that is not in the list."""
    meta = sessions_meta.get(session_id)
    if meta is None:
        return None
    current = meta.account_id or default_account_id() or ""
    return current, meta.fallback_from or current


@dataclass(frozen=True)
class _Lines:
    """What the usage log says about the account a tab belongs to (at its line, within `ahead_pct` of it) and about
    the account it would be moved to, or runs on now (at its own line). None = not known."""
    limited: bool | None = None
    near: bool | None = None
    target_over: bool | None = None


def _is_over_hold_line(rows: list[dict], account: str, now: float) -> bool | None:
    """Whether `account` is at the line where the account hold stops its tabs (False when it has none)."""
    # Imported here: `account_hold` imports this package (its break and its settings), so a module-level import of it
    # would make the two packages import each other.
    from backend.account_hold.hold_judgement import is_over_line  # noqa: PLC0415
    from backend.account_hold.hold_settings import read_rules as read_hold_rules  # noqa: PLC0415
    return is_over_line(rows, read_hold_rules().get(account), now)


def _lines(rows: list[dict], rule: FallbackRule | None, current: str, home: str, now: float) -> _Lines:
    if rule is None:
        return _Lines()
    target = rule.to_account if current == home else current
    return _Lines(limited=home_is_limited(rows, rule, now), near=home_is_near(rows, rule, now),
                  target_over=_is_over_hold_line(rows, target, now))


def _clear_pause(session_id: str, meta: SessionDef) -> None:
    """Forget that the tab was asked to come to a break."""
    _gave_up_on.discard(session_id)
    if meta.pause_asked_at is not None:
        meta.pause_asked_at = None
        save_sessions_meta()


async def _pause(session_id: str, meta: SessionDef, wanted: Move, tab_break: TabBreak, current: str, home: str,
                 rule: FallbackRule | None, now: float) -> None:
    """A tab that must move whatever its cache is (`wanted` is `urgent_move`) but is not at a break: ask it once to
    come to one when it keeps answering, and say once that the request has gone unanswered for too long."""
    if meta.pause_asked_at is not None:
        if session_id not in _gave_up_on and pause_overdue(meta.pause_asked_at, now):
            _gave_up_on.add(session_id)
            logger.info("account fallback: no break after asking to pause session=%s account=%s waited_sec=%d",
                        session_id, current, now - meta.pause_asked_at)
        return
    if rule is None or meta.owes_carry_on or not should_ask_to_pause(wanted=wanted, blocked_by=tab_break.blocked_by,
                                                                     stopped_by_limit=tab_break.stop is not None,
                                                                     asked_at=meta.pause_asked_at):
        return                                   # one request per tab: one it was sent already brings it to a break
    meta.pause_asked_at = now
    save_sessions_meta()
    request = (pause_envelope(current, rule.to_account, display_name_of(rule.to_account)) if wanted is Move.MOVE else
               return_pause_envelope(current, home, display_name_of(current), display_name_of(home)))
    if not await send_to_tab(session_id, request):
        _clear_pause(session_id, meta)                                   # not delivered: the next look asks again
        return
    meta.owes_carry_on = True
    save_sessions_meta()
    logger.info("account fallback: asked to pause session=%s account=%s", session_id, current)


def _log_move(session_id: str, current: str, target: str, action: Move, lines: _Lines, tab_break: TabBreak,
              cold: tuple[str, ...], returns_over_line: bool) -> None:
    """Say what was done to the tab and why: a move because the account is at its line, a move ahead of the line, a
    return because the account the tab ran on reached its own line, or a return (once the cache is cold)."""
    stopped, owed = tab_break.stop is not None, tab_break.owed is not None
    if action is Move.MOVE and lines.limited is True:
        logger.info("account fallback: moved session=%s from=%s to=%s stopped_by_limit=%s continuation_owed=%s",
                    session_id, current, target, stopped, owed)
    elif action is Move.MOVE:
        logger.info("account fallback: moved ahead session=%s from=%s to=%s cold=%s", session_id, current, target,
                    ",".join(cold))
    elif returns_over_line:
        logger.info("account fallback: back because %s is at its line session=%s from=%s to=%s stopped_by_limit=%s "
                    "continuation_owed=%s", current, session_id, current, target, stopped, owed)
    else:
        logger.info("account fallback: returned session=%s from=%s to=%s cold=%s stopped_by_limit=%s "
                    "continuation_owed=%s", session_id, current, target, ",".join(cold), stopped, owed)


async def _move(session_id: str, current: str, home: str, rule: FallbackRule | None, action: Move,
                tab_break: TabBreak, lines: _Lines, cold: tuple[str, ...]) -> bool:
    """Do `action` on the tab. True when it moved. A move that fails leaves the tab on the account it was on, and the
    next look tries again. A tab that was stopped by a limit, or still owed the continuation Claude Code booked at a
    limit (the move starts claude again, which loses it), or owed a message to carry on (`owes_carry_on`: it was asked
    to come to a break), is told to carry on; a message that does not reach it stays owed."""
    moving = action is Move.MOVE
    target = rule.to_account if moving and rule is not None else home
    cut = LineageCut.THROUGH_TOOL_RESULTS if tab_break.stop is not None else LineageCut.CLEAN_TURN
    try:
        await move_tab_account(session_id, target, cut=cut, fallback_from=home if moving else None)
    except HTTPException as error:
        logger.warning("account fallback: could not move session=%s from=%s to=%s: %s", session_id, current, target,
                       error.detail)
        return False
    _log_move(session_id, current, target, action, lines, tab_break, cold,
              returns_over_line=returns_over_target_line(current=current, home=home, rule=rule, limited=lines.limited,
                                                         target_over_line=lines.target_over))
    _last_note.pop(session_id, None)
    meta = sessions_meta.get(session_id)
    if meta is None:
        return True
    _clear_pause(session_id, meta)
    limit = tab_break.stop is not None or tab_break.owed is not None
    if limit or meta.owes_carry_on:
        meta.owes_carry_on = True                # kept until the message is taken: the hold's next look sends it again
        save_sessions_meta()
        if await send_to_tab(session_id, carry_on_envelope(current, target, LIMIT if limit else PAUSE)):
            meta.owes_carry_on = False
            save_sessions_meta()
    return True


def _stay_note(session_id: str, current: str, home: str, rule: FallbackRule | None, lines: _Lines,
               cold: tuple[str, ...] | None, pinned: bool) -> str | None:
    """Why a tab stays on purpose, None when it does not: it is on the fallback account and goes back when its cache is
    cold (`cold` = None when the tab was not read), or it would be moved (ahead of the line, or at it) to an account
    that is at its own line."""
    if rule is None or pinned:
        return None
    if current != home and lines.near is False and cold == ():
        return f"returns when cold session={session_id} account={current} home={home}"
    if current == home and lines.limited is False and lines.near is True and lines.target_over is True:
        return (f"not moved ahead of the line because {rule.to_account} is at its line session={session_id} "
                f"account={current}")
    if current == home and lines.limited is True and lines.target_over is True:
        return (f"not moved because {rule.to_account} is at its line too session={session_id} account={current}")
    return None


def _say_stay(session_id: str, note: str | None) -> None:
    """Log the note once, and forget it when the tab no longer stays for that reason."""
    if note is None:
        _last_note.pop(session_id, None)
    elif _last_note.get(session_id) != note:
        _last_note[session_id] = note
        logger.info("account fallback: %s", note)


async def _look(session_id: str, rows: list[dict], now: float) -> bool:
    """Look at one tab and move it if it must. True when it moved."""
    accounts = _accounts_of(session_id)
    meta = sessions_meta.get(session_id)
    if accounts is None or meta is None:
        return False
    current, home = accounts
    rule = read_rules().get(home)
    lines = _lines(rows, rule, current, home, now)
    urgent = urgent_move(current=current, home=home, rule=rule, limited=lines.limited,
                         target_over_line=lines.target_over, pinned=meta.account_pinned)
    if rule is None or meta.account_pinned or (lines.limited is not None and urgent is Move.STAY):
        _clear_pause(session_id, meta)                                   # nothing needs the tab to move now
    if meta.sleep is not None:
        return False
    wanted = decide(current=current, home=home, rule=rule, limited=lines.limited, at_break=True,
                    pinned=meta.account_pinned, near=lines.near, target_over_line=lines.target_over)
    if wanted is Move.STAY:
        _last_blocked.pop(session_id, None)
        _say_stay(session_id, _stay_note(session_id, current, home, rule, lines, None, meta.account_pinned))
        return False
    with claimed(session_id) as mine:
        if not mine:
            return False
        tab_break = await asyncio.to_thread(read_tab_break, session_id)
        cold = cold_reasons(quiet_minutes=tab_break.quiet_minutes)
        action = decide(current=current, home=home, rule=rule, limited=lines.limited, at_break=tab_break.at_break,
                        pinned=meta.account_pinned, near=lines.near, cold=bool(cold), target_over_line=lines.target_over)
        if _last_blocked.get(session_id) != tab_break.blocked_by:
            _last_blocked[session_id] = tab_break.blocked_by
            if tab_break.blocked_by:
                logger.info("account fallback: waits session=%s account=%s reasons=%s", session_id, current,
                            ",".join(tab_break.blocked_by))
        if action is Move.STAY:
            await _pause(session_id, meta, urgent, tab_break, current, home, rule, now)
            if tab_break.at_break:
                _say_stay(session_id, _stay_note(session_id, current, home, rule, lines, cold, meta.account_pinned))
            return False
        return await _move(session_id, current, home, rule, action, tab_break, lines, cold)


async def tick() -> list[str]:
    """Look over every tab once. → the tabs that were moved or brought back."""
    if not read_rules() and not any(meta.fallback_from or meta.pause_asked_at is not None
                                    for meta in sessions_meta.values()):
        return []
    rows = await asyncio.to_thread(read_all_rate_limits_tail)
    now = time.time()
    return [session_id for session_id in list(sessions_meta) if await _look(session_id, rows, now)]


async def move_before_wake(session_id: str) -> None:
    """Called before a sleeping tab is reopened: when the account it belongs to is at its line, or near it (`ahead_pct`),
    the tab is moved to the account its fallback names and wakes there; when it runs on the fallback account and the
    account it belongs to is clear of its line, or the account it runs on has reached its own line, it is brought back
    and wakes there. It is asleep, so it is at a break by definition, and its cache is cold."""
    accounts = _accounts_of(session_id)
    if accounts is None:
        return
    current, home = accounts
    rule = read_rules().get(home)
    if rule is None and current == home:
        return
    rows = await asyncio.to_thread(read_all_rate_limits_tail)
    now = time.time()
    lines = _lines(rows, rule, current, home, now)
    wanted = decide(current=current, home=home, rule=rule, limited=lines.limited, at_break=True,
                    pinned=sessions_meta[session_id].account_pinned, near=lines.near, target_over_line=lines.target_over)
    if wanted is Move.STAY:
        return
    moving = wanted is Move.MOVE
    target = rule.to_account if moving and rule is not None else home
    with claimed(session_id) as mine:
        if not mine:
            return
        stop = await asyncio.to_thread(sleeping_stop, session_id)
        cut = LineageCut.THROUGH_TOOL_RESULTS if stop is not None else LineageCut.CLEAN_TURN
        try:
            await move_tab_account(session_id, target, cut=cut, fallback_from=home if moving else None)
        except HTTPException as error:
            logger.warning("account fallback: a sleeping tab stays on its account session=%s: %s", session_id,
                           error.detail)
            return
        _clear_pause(session_id, sessions_meta[session_id])
        _last_note.pop(session_id, None)
        if moving:
            logger.info("account fallback: moved%s session=%s from=%s to=%s asleep=1",
                        "" if lines.limited is True else " ahead", session_id, current, target)
        elif returns_over_target_line(current=current, home=home, rule=rule, limited=lines.limited,
                                      target_over_line=lines.target_over):
            logger.info("account fallback: back because %s is at its line session=%s from=%s to=%s asleep=1", current,
                        session_id, current, target)
        else:
            logger.info("account fallback: returned session=%s from=%s to=%s asleep=1", session_id, current, target)


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
