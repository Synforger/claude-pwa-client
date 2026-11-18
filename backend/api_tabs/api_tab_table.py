"""The tabs and wallets that `config.json` declares under `api_tabs` and `api_accounts`, read once per configuration.

An API tab has no Claude Code behind it: a program outside the client calls the Messages API itself and appends the
conversation to a record file, which the client only shows (see `docs/reference/api-tabs.md`). The tabs live in a table
of their own, never in `sessions_meta`, so that no patrol (which walks `sessions_meta`) can ever reach one.

`current_table()` is the single reader: the list, the overview, the subscription filter, the replay and the message door
all ask it, so they cannot disagree about which ids exist. It parses again whenever `config.get_config()` hands out a
new object (= the backend started, or `config.reload_config` ran). Used by every door that names an API tab.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import backend._common.config as config

logger = logging.getLogger(__name__)

#: Every API tab id starts with this, so that it is told from a Claude tab's `ses_` id at a glance.
API_TAB_ID_PREFIX = "api_"
#: The account an API tab names when its row says none: the wallet the list shows in its account column.
DEFAULT_WALLET = "api"
#: Names go into the id, which a subscription query splits on `,` and `:` and the screen puts into a URL as it is.
NAME_RE = re.compile(r"[a-z0-9-]+")


@dataclass(frozen=True)
class ApiTab:
    """One tab of `api_tabs`: its id (`api_<name>`), the name it was declared under, the title the list shows, the agent
    whose tree it sits in, the wallet it names and the record file the program writes."""
    id: str
    name: str
    title: str
    agent_id: str
    account: str
    record: Path


@dataclass(frozen=True)
class ApiAccount:
    """One wallet of `api_accounts`: its name, the name the screen shows and the file that holds this month's spend
    (None when the wallet declares none)."""
    name: str
    display_name: str
    spend: Path | None


class ApiTabTable:
    """The API tabs and wallets of one configuration, with the lines the loader warned about."""

    def __init__(self, tabs: list[ApiTab], accounts: list[ApiAccount], problems: list[str]) -> None:
        self.tabs = tabs
        self.accounts = accounts
        self.problems = problems
        self._by_id = {tab.id: tab for tab in tabs}
        self._wallets = {account.name: account for account in accounts}

    @classmethod
    def from_config(cls, settings: dict[str, Any]) -> "ApiTabTable":
        """The table a configuration declares. A row that is not valid is left out with a warning line, and the rest
        stay (= one bad row does not take the other tabs away)."""
        problems: list[str] = []
        accounts = _read_accounts(settings.get("api_accounts"), problems)
        agent_ids = set(settings.get("agents") or {})
        tabs = _read_tabs(settings.get("api_tabs"), agent_ids, {account.name for account in accounts}, problems)
        return cls(tabs, accounts, problems)

    def ids(self) -> list[str]:
        return [tab.id for tab in self.tabs]

    def tab(self, tab_id: str) -> ApiTab | None:
        return self._by_id.get(tab_id)

    def find(self, receiver: str) -> ApiTab | None:
        """The tab a message receiver (= an id or a title) names, None when it names none of them."""
        if receiver in self._by_id:
            return self._by_id[receiver]
        return next((tab for tab in self.tabs if tab.title == receiver), None)

    def account(self, name: str) -> ApiAccount | None:
        return self._wallets.get(name)


def _read_accounts(raw: object, problems: list[str]) -> list[ApiAccount]:
    if raw is None:
        return []
    if not isinstance(raw, dict):
        problems.append(f"api account: skipped api_accounts: must be an object, got {type(raw).__name__}")
        return []
    accounts: list[ApiAccount] = []
    for name, entry in raw.items():
        if not (isinstance(name, str) and NAME_RE.fullmatch(name)):
            problems.append(f"api account: skipped {name!r}: the name must match {NAME_RE.pattern}")
            continue
        if not isinstance(entry, dict):
            problems.append(f"api account: skipped {name}: must be an object")
            continue
        display_name, spend = entry.get("display_name"), entry.get("spend")
        if spend is not None and not (isinstance(spend, str) and Path(spend).expanduser().is_absolute()):
            problems.append(f"api account: skipped {name}: spend must be an absolute path")
            continue
        accounts.append(ApiAccount(
            name=name,
            display_name=display_name if isinstance(display_name, str) and display_name else name,
            spend=Path(spend).expanduser() if isinstance(spend, str) else None,
        ))
    return accounts


def _read_tabs(raw: object, agent_ids: set[str], wallet_names: set[str], problems: list[str]) -> list[ApiTab]:
    if raw is None:
        return []
    if not isinstance(raw, dict):
        problems.append(f"api tab: skipped api_tabs: must be an object, got {type(raw).__name__}")
        return []
    tabs: list[ApiTab] = []
    for name, entry in raw.items():
        if not (isinstance(name, str) and NAME_RE.fullmatch(name)):
            problems.append(f"api tab: skipped {name!r}: the name must match {NAME_RE.pattern}")
            continue
        if not isinstance(entry, dict):
            problems.append(f"api tab: skipped {name}: must be an object")
            continue
        agent_id, record = entry.get("agent_id"), entry.get("record")
        if not (isinstance(agent_id, str) and agent_id in agent_ids):
            problems.append(f"api tab: skipped {name}: agent_id {agent_id!r} is not in agents")
            continue
        if not (isinstance(record, str) and Path(record).expanduser().is_absolute()):
            problems.append(f"api tab: skipped {name}: record must be an absolute path")
            continue
        title, account = entry.get("title"), entry.get("account")
        if account is not None and not (isinstance(account, str) and NAME_RE.fullmatch(account)):
            problems.append(f"api tab: skipped {name}: account must match {NAME_RE.pattern}")
            continue
        account = account or DEFAULT_WALLET
        if account not in wallet_names:
            problems.append(f"api tab: {name} names account {account}, which is not in api_accounts (no spend is shown)")
        tabs.append(ApiTab(
            id=f"{API_TAB_ID_PREFIX}{name}",
            name=name,
            title=title if isinstance(title, str) and title.strip() else name,
            agent_id=agent_id,
            account=account,
            record=Path(record).expanduser(),
        ))
    return tabs


# The table of the configuration `_loaded_from`; it is read again when the configuration object changes.
_loaded_from: dict[str, Any] | None = None
_loaded: ApiTabTable = ApiTabTable([], [], [])


def current_table() -> ApiTabTable:
    """The table of the configuration now in force. Parsing it again (and writing the load lines of the log) happens
    only when the configuration was read again, so the call is cheap enough for every door."""
    global _loaded_from, _loaded
    settings = config.get_config()
    if settings is not _loaded_from:
        _loaded = ApiTabTable.from_config(settings)
        _loaded_from = settings
        _log_load(_loaded)
    return _loaded


def _log_load(table: ApiTabTable) -> None:
    for problem in table.problems:
        logger.warning(problem)
    for account in table.accounts:
        logger.info("api account: loaded %s spend=%s", account.name, account.spend)
    for tab in table.tabs:
        logger.info("api tab: loaded %s record=%s exists=%s", tab.id, tab.record, tab.record.is_file())


def is_api_tab(tab_id: str) -> bool:
    """Whether `tab_id` is an API tab of the configuration now in force."""
    return tab_id.startswith(API_TAB_ID_PREFIX) and current_table().tab(tab_id) is not None
