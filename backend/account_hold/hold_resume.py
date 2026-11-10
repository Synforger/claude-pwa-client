"""Resumes the tabs the account hold stopped, once the account they belong to is clear of its line. A tab the account
fallback moved to the held account stays stopped while both accounts are at their lines; when the account it belongs to
drops below its line, this brings the tab back to that account (the fallback's own move, which a message from another
tab starts too) and sends it the message the operator's "continue" sends (`hold_continue.continue_tab`). The held
account is not used: the tab leaves it before it carries on. While the account it belongs to is still at its line, or
its usage is not known, nothing changes and the tab stays stopped for the operator to continue.

Used by `hold_patrol.py`.
"""
from __future__ import annotations

import logging

from backend._common.state import sessions_meta
from backend.account_fallback import fallback_settings
from backend.account_fallback.fallback_judgement import home_is_limited, home_is_near
from backend.account_fallback.fallback_patrol import move_before_wake
from backend.account_hold.hold_continue import continue_tab
from backend.account_hold.hold_judgement import is_over_line, resumes_on_home
from backend.account_hold.hold_settings import HoldRule
from backend.account_hold.hold_tabs import account_of

logger = logging.getLogger(__name__)


async def _resume(session_id: str, rows: list[dict], hold_rules: dict[str, HoldRule], now: float) -> bool:
    """Bring one stopped tab back to the account it belongs to and continue it, when its account is clear. True when it
    carries on; False when it stays (the next look tries again)."""
    meta = sessions_meta.get(session_id)
    current = account_of(meta) if meta is not None else None
    if meta is None or meta.held_at is None or current is None:
        return False
    home = meta.fallback_from or current
    rule = fallback_settings.read_rules().get(home)
    if rule is None:
        return False
    if not resumes_on_home(current=current, home=home, rule=rule, limited=home_is_limited(rows, rule, now),
                           near=home_is_near(rows, rule, now), pinned=meta.account_pinned,
                           target_over_line=is_over_line(rows, hold_rules.get(current), now)):
        return False
    if current != home:
        await move_before_wake(session_id)
        if account_of(meta) != home:                         # the move was not made (the tab is busy, or it failed)
            return False
    if not await continue_tab(session_id, home):
        return False
    logger.info("account hold: resumed on %s session=%s from=%s", home, session_id, current)
    return True


async def resume_on_home(rows: list[dict], hold_rules: dict[str, HoldRule], now: float) -> list[str]:
    """Look at every stopped tab once. → the tabs that were brought back to their own account and continued."""
    held = [session_id for session_id, meta in list(sessions_meta.items()) if meta.held_at is not None]
    return [session_id for session_id in held if await _resume(session_id, rows, hold_rules, now)]
