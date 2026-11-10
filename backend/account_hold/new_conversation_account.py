"""The account a tab's new conversation starts on, when the tab is started again with a new conversation (the rollover,
or the operator's restart). A new conversation has no cache to lose, so this is where a tab moves most cheaply: it
starts on the account it may run on now, the same one a sleeping tab wakes on (`hold_mail.clear_account_for`). A tab
no account is clear for starts where it is; the account hold stops it at its next break. A sleeping or stopped tab is
not started this way, and is left alone.

The marks the account features keep for the conversation that ended are dropped: the mark of the record the client
wrote into the fallback account (`fallback_copy`; the file stays, as the record of that conversation, opened from the
history, and must not be deleted by a later move), the "carry on" owed (the rollover's first message hands the work
over) and the requests for a break or a stop (the patrols ask the new conversation again when it still needs it).

Used by `routes/sessions.py::restart_session`, between the end of the claude and the start of the new one.
"""
from __future__ import annotations

import logging
import time

from backend._common.state import save_sessions_meta, sessions_meta
from backend.account_hold.hold_mail import clear_account_for
from backend.account_hold.hold_settings import read_rules
from backend.account_hold.hold_tabs import account_of
from backend.usage.usage import read_all_rate_limits_tail

logger = logging.getLogger(__name__)


def choose_account_for_new_conversation(session_id: str) -> str | None:
    """Set the account the tab's new conversation starts on, and drop the marks of the conversation that ended.
    → the account it was moved to; None when it stays. Blocking (the usage rows, the settings)."""
    meta = sessions_meta.get(session_id)
    current = account_of(meta) if meta is not None else None
    if meta is None or current is None or meta.sleep is not None or meta.held_at is not None:
        return None
    meta.fallback_copy = None
    meta.owes_carry_on = False
    meta.pause_asked_at = None
    meta.hold_asked_at = None
    target = clear_account_for(meta, read_all_rate_limits_tail(), read_rules(), time.time(), for_messages=True)
    moved = target is not None and target != current
    if moved:
        home = meta.fallback_from or current
        meta.account_id = target
        meta.fallback_from = home if target != home else None
        logger.info("new conversation: account session=%s from=%s to=%s", session_id, current, target)
    save_sessions_meta()
    return target if moved else None
