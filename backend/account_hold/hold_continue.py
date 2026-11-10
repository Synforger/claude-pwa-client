"""Continues the tabs the account hold stopped, when the operator asks (= `POST /accounts/{account}/continue`), and is
where every continue of a stopped tab ends (`continue_tab`, `release_tab`), which `hold_resume.py` uses too.

A stopped tab the client owes a message to carry on (`owes_carry_on`: it was asked to come to a break, or a usage limit
stopped it) is sent that message, which wakes it in the same conversation. A tab that had nothing left to do when it was
stopped is only released: its marks go, it sleeps on, and nothing is sent. The operator's continue is refused while a
stopped tab on the account has no account clear to run on (the account's own hold line, or for an account with a
fallback, both accounts at their lines), and while that is not known.

Used by `routes/account_hold.py` and `hold_resume.py`.
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass

from backend._common.state import SessionDef, save_sessions_meta, sessions_meta
from backend.account_hold.hold_envelope import continue_envelope
from backend.account_hold.hold_judgement import reached_line_pct
from backend.account_hold.hold_mail import clear_account_for
from backend.account_hold.hold_settings import read_rules
from backend.account_hold.hold_tabs import held_tabs
from backend.accounts.client_message import send_to_tab
from backend.accounts.tab_claim import claimed
from backend.usage.usage import read_all_rate_limits_tail

logger = logging.getLogger(__name__)


class StillAtLine(Exception):
    """A stopped tab on the account has no account clear to run on, so the account's tabs are not continued."""

    def __init__(self, account: str, line_pct: int) -> None:
        super().__init__(f"the usage of {account} is still at {line_pct}% or more")
        self.account = account
        self.line_pct = line_pct


@dataclass(frozen=True)
class Continued:
    """The tabs a continue reached or released (their marks are off) and the tabs it did not (the mark stays; ask
    again)."""
    continued: tuple[str, ...]
    failed: tuple[str, ...]


async def continue_account(account: str) -> Continued:
    """Continue every tab the account hold stopped on `account`. Raises `StillAtLine` while one of them has no account
    clear to run on. A tab that would carry on on another account is left to the patrol, which moves it there."""
    now = time.time()
    rules = read_rules()
    rows = read_all_rate_limits_tail()
    tabs = held_tabs(account)
    targets = {meta.id: clear_account_for(meta, rows, rules, now, for_messages=True) for meta in tabs}
    if any(target is None for target in targets.values()):
        rule = rules.get(account)
        raise StillAtLine(account, (reached_line_pct(rows, rule, now) if rule is not None else None) or 0)
    continued: list[str] = []
    failed: list[str] = []
    for meta in tabs:
        if targets[meta.id] != account:
            continue
        if not await continue_tab(meta.id, account):
            failed.append(meta.id)
            continue
        continued.append(meta.id)
        logger.info("account hold: continued session=%s account=%s", meta.id, account)
    return Continued(tuple(continued), tuple(failed))


def release_tab(meta: SessionDef) -> None:
    """Take the marks off a stopped tab that had nothing left to do: it sleeps on and is sent nothing."""
    meta.held_at = None
    meta.hold_asked_at = None
    save_sessions_meta()
    logger.info("account hold: released without a message session=%s (nothing was left to do)", meta.id)


async def continue_tab(session_id: str, account: str, *, stopped: bool = True) -> bool:
    """Carry one tab on: send the message that asks it to carry on when the client owes it one, or only release it
    when it was stopped with nothing left to do. `account` is the account the message names (= where the tab runs
    now); `stopped` is False for a tab that was asked to come to a break and then not stopped. True when the tab took the
    message, was released, or was continued by someone else meanwhile; False when it is being worked on by another
    feature or did not take the message (the marks stay, so the next call tries again)."""
    with claimed(session_id) as mine:
        live = sessions_meta.get(session_id)
        if not mine or live is None:
            return False
        if stopped and live.held_at is None:
            return True                                              # continued meanwhile by the patrol or the operator
        if not live.owes_carry_on:
            release_tab(live)
            return True
        if not await send_to_tab(session_id, continue_envelope(account, stopped=stopped)):
            return False
    live.held_at = None
    live.hold_asked_at = None
    live.owes_carry_on = False
    save_sessions_meta()
    return True
