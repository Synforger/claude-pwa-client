"""Which tabs run on an account and which of them the account hold stopped. Reads the tab list (`sessions_meta`) and
nothing else.

Used by `hold_patrol.py`, `hold_continue.py` and the settings screen's backend (`settings/settings_view.py`).
"""
from __future__ import annotations

from backend._common.config import default_account_id
from backend._common.state import SessionDef, sessions_meta


def account_of(meta: SessionDef) -> str | None:
    """The account the tab runs on now (the tab's own, or the default account for a tab that names none)."""
    return meta.account_id or default_account_id()


def held_tabs(account: str) -> list[SessionDef]:
    """The tabs on `account` that the account hold stopped and nobody has continued yet."""
    return [meta for meta in list(sessions_meta.values()) if meta.held_at is not None and account_of(meta) == account]
