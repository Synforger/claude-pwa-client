"""Continues the tabs the account hold stopped, when the operator asks (= `POST /accounts/{account}/continue`). Each
stopped tab on the account is sent the message that asks it to carry on, which wakes it in the same conversation, and
loses its mark. It is refused while the usage of the account is still at the line of today.

Used by `routes/account_hold.py`.
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass

from backend._common.state import save_sessions_meta, sessions_meta
from backend.account_hold.hold_envelope import continue_envelope
from backend.account_hold.hold_judgement import hold_line_pct, is_over_line
from backend.account_hold.hold_settings import read_rules
from backend.account_hold.hold_tabs import held_tabs
from backend.accounts.client_message import send_to_tab
from backend.accounts.tab_claim import claimed
from backend.usage.usage import read_all_rate_limits_tail

logger = logging.getLogger(__name__)


class StillAtLine(Exception):
    """The usage of the account is still at the line of today, so its tabs are not continued."""

    def __init__(self, account: str, line_pct: int) -> None:
        super().__init__(f"the usage of {account} is still at {line_pct}% or more")
        self.account = account
        self.line_pct = line_pct


@dataclass(frozen=True)
class Continued:
    """The tabs a continue reached (their marks are off) and the tabs it did not (the mark stays; ask again)."""
    continued: tuple[str, ...]
    failed: tuple[str, ...]


async def continue_account(account: str) -> Continued:
    """Continue every tab the account hold stopped on `account`. Raises `StillAtLine` while the usage of the account is
    at the line of today."""
    now = time.time()
    rule = read_rules().get(account)
    if rule is not None and is_over_line(read_all_rate_limits_tail(), rule, now):
        raise StillAtLine(account, hold_line_pct(rule, now) or 0)
    continued: list[str] = []
    failed: list[str] = []
    for meta in held_tabs(account):
        session_id = meta.id
        with claimed(session_id) as mine:
            sent = mine and await send_to_tab(session_id, continue_envelope(account))
        if not sent:
            failed.append(session_id)
            continue
        live = sessions_meta.get(session_id)
        if live is not None:
            live.held_at = None
            live.hold_asked_at = None
            save_sessions_meta()
        continued.append(session_id)
        logger.info("account hold: continued session=%s account=%s", session_id, account)
    return Continued(tuple(continued), tuple(failed))
