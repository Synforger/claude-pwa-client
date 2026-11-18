"""The rows an API tab appears as in the doors that list the tabs: the list (`GET /sessions`), the overview (the
`overview` channel and `GET /sessions/overview`), the status channel the top bar reads, and the settings screen's wallets.

Every row is built from the one table (`api_tab_table.current_table`) and from what the stream already holds
(`api_tab_stream.stream`), so building a row never reads a file. An API tab shows no progress marks (it is never busy and
never waits for input): only its name and how much of the context its conversation holds. Used by `routes/sessions.py`,
`routes/overview.py` and `settings/settings_view.py`.
"""
from __future__ import annotations

from datetime import datetime

from backend._common.state import SessionDef, session_last_seen_at
from backend.api_tabs.api_tab_stream import stream
from backend.api_tabs.api_tab_table import ApiTab, current_table

#: The `kind` an API tab's rows carry (a Claude tab's rows carry none).
API_KIND = "api"


def list_row(tab: ApiTab) -> dict:
    """The tab as `GET /sessions` lists it: a Claude tab's row shape with neutral values, the wallet as its account, and
    its context amount."""
    definition = SessionDef(id=tab.id, agent_id=tab.agent_id, title=tab.title, created_at=0, notify_mode="off",
                            account_id=tab.account)
    return {**definition.to_dict(), "kind": API_KIND, "tier": None, "account_on_wake": None,
            "context_tokens": stream.context_tokens(tab.id)}


def overview_row(tab: ApiTab) -> dict:
    """The tab in the overview: the keys of a Claude tab's row (never busy, never waiting) and its context amount."""
    return {
        "kind": API_KIND,
        "busy": False,
        "last_seen_at": session_last_seen_at.get(tab.id),
        "waiting_input": False,
        "tier": None,
        "asleep": False,
        "account_id": tab.account,
        "fallback_from": None,
        "account_pinned": False,
        "account_on_wake": None,
        "context_tokens": stream.context_tokens(tab.id),
    }


def status_row(tab: ApiTab, now: datetime) -> dict:
    """The tab in the status channel: only its context amount and its wallet's spend this month (None when there is no
    figure). It is a row of its own kind, never a Claude row with empty fields, so the bar cannot show a `NaN%`."""
    spend = stream.spend(tab.account, now)
    return {"kind": API_KIND, "context_tokens": stream.context_tokens(tab.id),
            "spend": None if spend is None else spend.to_dict()}


def list_rows() -> list[dict]:
    return [list_row(tab) for tab in current_table().tabs]


def overview_rows() -> dict[str, dict]:
    return {tab.id: overview_row(tab) for tab in current_table().tabs}


def status_rows(now: datetime | None = None) -> dict[str, dict]:
    now = datetime.now().astimezone() if now is None else now
    return {tab.id: status_row(tab, now) for tab in current_table().tabs}


def wallet_views(now: datetime | None = None) -> list[dict]:
    """The wallets as the settings screen shows them: read-only, with this month's spend (None when there is no figure)."""
    now = datetime.now().astimezone() if now is None else now
    views = []
    for wallet in current_table().accounts:
        spend = stream.spend(wallet.name, now)
        views.append({"id": wallet.name, "display_name": wallet.display_name,
                      "spend": None if spend is None else spend.to_dict()})
    return views
