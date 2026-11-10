"""Continues the tabs the account hold stopped, when the operator asks (= `POST /accounts/{account}/continue`). Each
stopped tab on the account is sent the message that asks it to carry on, which wakes it in the same conversation, and
loses its mark. It is refused while the usage of the account is still at the line of today. `continue_tab` is the
sending of that message to one tab, which `hold_resume.py` uses too.

Used by `routes/account_hold.py` and `hold_resume.py`.
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass

from backend._common.state import save_sessions_meta, sessions_meta
from backend.account_hold.hold_envelope import continue_envelope
from backend.account_hold.hold_judgement import is_over_line, reached_line_pct
from backend.account_hold.hold_settings import read_rules
from backend.account_hold.hold_tabs import held_tabs
from backend.accounts.client_message import send_to_tab
from backend.accounts.tab_claim import claimed
from backend.usage.usage import read_all_rate_limits_tail

logger = logging.getLogger(__name__)


class StillAtLine(Exception):
    """The usage of the account is still at a line of today, so its tabs are not continued."""

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
    at a line of today."""
    now = time.time()
    rule = read_rules().get(account)
    rows = read_all_rate_limits_tail()
    if rule is not None and is_over_line(rows, rule, now):
        raise StillAtLine(account, reached_line_pct(rows, rule, now) or 0)
    continued: list[str] = []
    failed: list[str] = []
    for meta in held_tabs(account):
        if not await continue_tab(meta.id, account):
            failed.append(meta.id)
            continue
        continued.append(meta.id)
        logger.info("account hold: continued session=%s account=%s", meta.id, account)
    return Continued(tuple(continued), tuple(failed))


async def continue_tab(session_id: str, account: str) -> bool:
    """Send one stopped tab the message that asks it to carry on, and take its marks off once it took it. `account` is
    the account the message names (= where the tab runs now). True when the tab took the message; False when it is
    being worked on by another feature or did not take it (the marks stay, so the next call tries again)."""
    with claimed(session_id) as mine:
        sent = mine and await send_to_tab(session_id, continue_envelope(account))
    if not sent:
        return False
    live = sessions_meta.get(session_id)
    if live is not None:
        live.held_at = None
        live.hold_asked_at = None
        save_sessions_meta()
    return True
