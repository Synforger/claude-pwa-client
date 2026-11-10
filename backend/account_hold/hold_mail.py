"""Keeps the messages from other tabs to a tab the account hold stopped, while no account is clear for the tab to run
on, so that a message does not wake the tab on an account at its line. `hold_resume.hand_over_kept` hands them over
once an account is clear; a tab that is woken all the same (by the operator) takes them at the next look.

`clear_account_for` is also the account a stopped tab is continued on (`hold_resume.py`).

Used by `routes/agent_messages.py` (which imports it where it is called: this package imports the fallback, which
imports the route) and `hold_resume.py`.
"""
from __future__ import annotations

import logging
import time

from backend._common.state import SessionDef, save_sessions_meta, sessions_meta
from backend.account_fallback import fallback_settings
from backend.account_fallback.fallback_judgement import home_is_limited, home_is_near
from backend.account_hold.hold_judgement import carry_on_account, is_over_line
from backend.account_hold.hold_settings import HoldRule, read_rules
from backend.account_hold.hold_tabs import account_of
from backend.usage.usage import read_all_rate_limits_tail

logger = logging.getLogger(__name__)


def clear_account_for(meta: SessionDef, rows: list[dict], hold_rules: dict[str, HoldRule], now: float, *,
                      for_messages: bool) -> str | None:
    """The account a stopped tab may run on now, None when there is none. For a tab whose account has a fallback, the
    account it belongs to or the one its fallback names, whichever is clear (`hold_judgement.carry_on_account`). For
    a tab whose account has none, its own account once that is clear of its hold line, but only `for_messages`: such a
    tab is continued by the operator, and only a message wakes it by itself."""
    current = account_of(meta)
    if current is None:
        return None
    home = meta.fallback_from or current
    rule = fallback_settings.read_rules().get(home)
    if rule is None:
        clear = for_messages and is_over_line(rows, hold_rules.get(current), now) is False
        return current if clear else None
    return carry_on_account(current=current, home=home, rule=rule, limited=home_is_limited(rows, rule, now),
                            near=home_is_near(rows, rule, now),
                            current_over=is_over_line(rows, hold_rules.get(current), now),
                            fallback_over=is_over_line(rows, hold_rules.get(rule.to_account), now),
                            pinned=meta.account_pinned)


def must_keep(session_id: str) -> bool:
    """Whether a message to the tab waits instead of waking it: the tab is stopped (asleep with the mark `held_at`) and
    no account is clear for it."""
    meta = sessions_meta.get(session_id)
    if meta is None or meta.held_at is None or meta.sleep is None:
        return False
    return clear_account_for(meta, read_all_rate_limits_tail(), read_rules(), time.time(), for_messages=True) is None


def keep(session_id: str, text: str) -> None:
    """Keep `text` (= a message already in its envelope) for the tab, after the ones kept before it."""
    meta = sessions_meta[session_id]
    meta.kept_messages.append(text)
    save_sessions_meta()
    logger.info("account hold: kept a message for a stopped tab session=%s account=%s kept=%d", session_id,
                account_of(meta), len(meta.kept_messages))
