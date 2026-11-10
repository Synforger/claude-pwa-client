"""Whether a tab may run now, and the messages kept for a sleeping tab that may not, so that nothing the client or
another tab sends wakes a tab on an account at its line. `hold_resume.hand_over_kept` hands the kept messages over once
the tab may run, or is awake.

`clear_account_for` is the account a sleeping tab may run on: the one it wakes on (the fallback's wake-up move takes it
there) and the one a stopped tab is continued on (`hold_resume.py`). `may_run` is the same question for any tab, asleep
or awake, which the limit resume asks before it sends its message.

Used by `routes/agent_messages.py`, `child_watch/watch_patrol.py` and `limit_resume/resume_patrol.py` (which import it
where they call it: this package imports the fallback, which sends its messages through the message route) and
`hold_resume.py`.
"""
from __future__ import annotations

import logging
import time

from backend._common.state import SessionDef, save_sessions_meta, sessions_meta
from backend.account_fallback import fallback_settings
from backend.account_fallback.fallback_judgement import home_is_limited, home_is_near
from backend.account_hold.hold_judgement import carry_on_account, is_over_line, runs_where_it_is
from backend.account_hold.hold_settings import HoldRule, read_rules
from backend.account_hold.hold_tabs import account_of
from backend.usage.usage import read_all_rate_limits_tail

logger = logging.getLogger(__name__)


def clear_account_for(meta: SessionDef, rows: list[dict], hold_rules: dict[str, HoldRule], now: float, *,
                      for_messages: bool) -> str | None:
    """The account a sleeping tab may run on now, None when there is none. A pinned tab on its own account runs there.
    For a tab
    whose account has a fallback, the account it belongs to or the one its fallback names, whichever is clear
    (`hold_judgement.carry_on_account`). For a tab whose account has none, its own account once that is clear of its
    hold line, but only `for_messages`: a stopped tab of such an account is continued by the operator, and only a
    message wakes it by itself."""
    current = account_of(meta)
    if current is None:
        return None
    home = meta.fallback_from or current
    if meta.account_pinned and current == home:
        return current
    rule = fallback_settings.read_rules().get(home)
    if rule is None:
        clear = for_messages and is_over_line(rows, hold_rules.get(current), now) is False
        return current if clear else None
    return carry_on_account(current=current, home=home, rule=rule, limited=home_is_limited(rows, rule, now),
                            near=home_is_near(rows, rule, now),
                            current_over=is_over_line(rows, hold_rules.get(current), now),
                            fallback_over=is_over_line(rows, hold_rules.get(rule.to_account), now),
                            pinned=meta.account_pinned)


def may_run(meta: SessionDef, rows: list[dict], hold_rules: dict[str, HoldRule], now: float) -> bool:
    """Whether the tab may run now: a sleeping one when an account is clear for it (it wakes there), an awake one
    where it is (`hold_judgement.runs_where_it_is`)."""
    if meta.sleep is not None:
        return clear_account_for(meta, rows, hold_rules, now, for_messages=True) is not None
    current = account_of(meta)
    if current is None:
        return False
    home = meta.fallback_from or current
    rule = fallback_settings.read_rules().get(home)
    return runs_where_it_is(current=current, home=home, rule=rule,
                            limited=home_is_limited(rows, rule, now) if rule is not None else None,
                            current_over=is_over_line(rows, hold_rules.get(current), now),
                            pinned=meta.account_pinned)


def must_keep(session_id: str) -> bool:
    """Whether a message to the tab waits instead of waking it: the tab sleeps (stopped by the hold or not) and no
    account is clear for it."""
    meta = sessions_meta.get(session_id)
    if meta is None or meta.sleep is None:
        return False
    return clear_account_for(meta, read_all_rate_limits_tail(), read_rules(), time.time(), for_messages=True) is None


def keep(session_id: str, text: str) -> None:
    """Keep `text` (= a message already in its envelope) for the tab, after the ones kept before it."""
    meta = sessions_meta[session_id]
    meta.kept_messages.append(text)
    save_sessions_meta()
    logger.info("account hold: kept a message for a sleeping tab session=%s account=%s kept=%d", session_id,
                account_of(meta), len(meta.kept_messages))
