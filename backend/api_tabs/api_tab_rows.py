"""The rows an API tab appears as in the doors that list the tabs: the list (`GET /sessions`), the overview (the
`overview` channel and `GET /sessions/overview`), the status channel the top bar reads, and the settings screen's wallets.

Every row is built from the one table (`api_tab_table.current_table`) and from what the stream already holds
(`api_tab_stream.stream` for the tabs of `api_tabs`, `api_tab_sources.sources` for the tabs a source lists), so building
a row never reads a file. An API tab shows no progress marks (it is never busy and never waits for input): only its name
and how much of the context its conversation holds, in percent when its source says the window's size. Used by
`routes/sessions.py`, `routes/overview.py` and `settings/settings_view.py`.
"""
from __future__ import annotations

from datetime import datetime

from dataclasses import dataclass

from backend._common.state import SessionDef, session_last_seen_at
from backend.api_tabs.api_spend import Spend, this_months
from backend.api_tabs.api_tab_sources import sources
from backend.api_tabs.api_tab_stream import stream
from backend.api_tabs.api_tab_table import ApiTab, current_table

#: The `kind` an API tab's rows carry (a Claude tab's rows carry none).
API_KIND = "api"
#: Whose spend a status row shows: the tab's own (its source counts per tab) or its wallet's (all the program spends).
SPEND_OF_TAB = "tab"
SPEND_OF_WALLET = "wallet"


@dataclass(frozen=True)
class TabFigures:
    """What a row shows of a tab now: the context amount, the size of the window (None when not known) and the spend
    this month with whose it is."""
    context_tokens: int | None
    context_window: int | None
    spend: Spend | None
    spend_scope: str


def figures_of(tab: ApiTab, now: datetime) -> TabFigures:
    """The figures of `tab`: from its source when a source lists it (= the source's own count, which is 0 right after it
    rolled the conversation over), else counted from its record, with its wallet's spend."""
    if tab.source is None:
        return TabFigures(stream.context_tokens(tab.id), None, stream.spend(tab.account, now), SPEND_OF_WALLET)
    listed = sources.figures(tab.source, tab.name)
    return TabFigures(context_tokens=None if listed is None else listed.context_tokens,
                      context_window=sources.context_window(tab.source),
                      spend=None if listed is None else this_months(listed.spend, now), spend_scope=SPEND_OF_TAB)


def _now() -> datetime:
    return datetime.now().astimezone()


def list_row(tab: ApiTab, now: datetime) -> dict:
    """The tab as `GET /sessions` lists it: a Claude tab's row shape with neutral values, the wallet as its account, and
    its context amount and window."""
    definition = SessionDef(id=tab.id, agent_id=tab.agent_id, title=tab.title, created_at=0, notify_mode="off",
                            account_id=tab.account)
    figures = figures_of(tab, now)
    return {**definition.to_dict(), "kind": API_KIND, "tier": None, "account_on_wake": None,
            "context_tokens": figures.context_tokens, "context_window": figures.context_window}


def overview_row(tab: ApiTab, now: datetime) -> dict:
    """The tab in the overview: the keys of a Claude tab's row (never busy, never waiting), its title (a source may
    rename a tab while the list is on screen) and its context amount and window."""
    figures = figures_of(tab, now)
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
        "title": tab.title,
        "context_tokens": figures.context_tokens,
        "context_window": figures.context_window,
    }


def status_row(tab: ApiTab, now: datetime) -> dict:
    """The tab in the status channel: only its context amount and window, and its spend this month (None when there is
    no figure) with whose it is. It is a row of its own kind, never a Claude row with empty fields, so the bar cannot
    show a `NaN%`."""
    figures = figures_of(tab, now)
    return {"kind": API_KIND, "context_tokens": figures.context_tokens, "context_window": figures.context_window,
            "spend": None if figures.spend is None else figures.spend.to_dict(), "spend_scope": figures.spend_scope}


def list_rows(now: datetime | None = None) -> list[dict]:
    now = _now() if now is None else now
    return [list_row(tab, now) for tab in current_table().tabs]


def overview_rows(now: datetime | None = None) -> dict[str, dict]:
    now = _now() if now is None else now
    return {tab.id: overview_row(tab, now) for tab in current_table().tabs}


def status_rows(now: datetime | None = None) -> dict[str, dict]:
    now = _now() if now is None else now
    return {tab.id: status_row(tab, now) for tab in current_table().tabs}


def wallet_views(now: datetime | None = None) -> list[dict]:
    """The wallets as the settings screen shows them: read-only, with this month's spend (None when there is no figure)."""
    now = _now() if now is None else now
    views = []
    for wallet in current_table().accounts:
        spend = stream.spend(wallet.name, now)
        views.append({"id": wallet.name, "display_name": wallet.display_name,
                      "spend": None if spend is None else spend.to_dict()})
    return views
