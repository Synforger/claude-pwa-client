"""The tabs and wallets that `config.json` declares under `api_tabs` and `api_accounts`, and the tabs that the programs
declared under `api_tab_sources` list in files of their own.

An API tab has no Claude Code behind it: a program outside the client calls the Messages API itself and appends the
conversation to a record file, which the client only shows (see `docs/reference/api-tabs.md`). The tabs live in a table
of their own, never in `sessions_meta`, so that no patrol (which walks `sessions_meta`) can ever reach one.

`current_table()` is the single reader: the list, the overview, the subscription filter, the replay and the message door
all ask it, so they cannot disagree about which ids exist. It builds the table again whenever `config.get_config()`
hands out a new object (= the backend started, or `config.reload_config` ran) or a source's file lists other tabs
(`api_tab_sources.sources.identity_version`); a change of a figure only (a context amount, a spend) does not rebuild it.
Used by every door that names an API tab.
"""
from __future__ import annotations

import logging
import re
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import backend._common.config as config
from backend.api_tabs.api_tab_sources import ApiTabSources, sources

logger = logging.getLogger(__name__)

#: Every API tab id starts with this, so that it is told from a Claude tab's `ses_` id at a glance.
API_TAB_ID_PREFIX = "api_"
#: The account an API tab names when its row says none: the wallet the list shows in its account column.
DEFAULT_WALLET = "api"
#: Names go into the id, which a subscription query splits on `,` and `:` and the screen puts into a URL as it is.
NAME_RE = re.compile(r"[a-z0-9-]+")


@dataclass(frozen=True)
class ApiTab:
    """One API tab: its id (`api_<name>`), the name it was declared or listed under, the title the list shows, the agent
    whose tree it sits in, the wallet it names, the record file the program writes, and the source that lists it (None
    for a row of `api_tabs`: its context amount is counted from its record; a source's tab has its amount from the
    source)."""
    id: str
    name: str
    title: str
    agent_id: str
    account: str
    record: Path
    source: str | None = None


@dataclass(frozen=True)
class ApiTabSource:
    """One entry of `api_tab_sources`: a program's file that lists its tabs, the agent whose tree they sit in, the
    wallet they name, and the settings file the settings screen may write (None when the screen offers no setting).
    Both paths come from the client's own configuration, never from the program's file."""
    name: str
    tabs: Path
    agent_id: str
    account: str
    settings: Path | None


@dataclass(frozen=True)
class ApiAccount:
    """One wallet of `api_accounts`: its name, the name the screen shows and the file that holds this month's spend
    (None when the wallet declares none)."""
    name: str
    display_name: str
    spend: Path | None


class ApiTabTable:
    """The API tabs and wallets of one configuration, with the lines the loader warned about."""

    def __init__(self, tabs: list[ApiTab], accounts: list[ApiAccount], problems: list[str],
                 sources: list[ApiTabSource] | None = None) -> None:
        self.tabs = tabs
        self.accounts = accounts
        self.problems = problems
        self.sources = sources or []
        self._by_id = {tab.id: tab for tab in tabs}
        self._wallets = {account.name: account for account in accounts}
        self._sources = {source.name: source for source in self.sources}

    @classmethod
    def from_config(cls, settings: dict[str, Any], listed: ApiTabSources | None = None) -> "ApiTabTable":
        """The table a configuration declares, with the tabs its sources list now (`listed`; none when not given). A
        row that is not valid is left out with a warning line, and the rest stay (= one bad row does not take the other
        tabs away). A source's row whose id is already taken (by `api_tabs`, or an earlier source) is left out too."""
        problems: list[str] = []
        accounts = _read_accounts(settings.get("api_accounts"), problems)
        agent_ids = set(settings.get("agents") or {})
        wallet_names = {account.name for account in accounts}
        tabs = _read_tabs(settings.get("api_tabs"), agent_ids, wallet_names, problems)
        declared = _read_sources(settings.get("api_tab_sources"), agent_ids, wallet_names, problems)
        if listed is not None:
            tabs = tabs + _source_tabs(declared, listed, {tab.id for tab in tabs}, problems)
        return cls(tabs, accounts, problems, declared)

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

    def source(self, name: str) -> ApiTabSource | None:
        return self._sources.get(name)

    def source_paths(self) -> dict[str, Path]:
        """The tab list file of each source, by name: what the stream looks at."""
        return {source.name: source.tabs for source in self.sources}


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


def _read_sources(raw: object, agent_ids: set[str], wallet_names: set[str], problems: list[str]) -> list[ApiTabSource]:
    if raw is None:
        return []
    if not isinstance(raw, dict):
        problems.append(f"api source: skipped api_tab_sources: must be an object, got {type(raw).__name__}")
        return []
    declared: list[ApiTabSource] = []
    for name, entry in raw.items():
        if not (isinstance(name, str) and NAME_RE.fullmatch(name)):
            problems.append(f"api source: skipped {name!r}: the name must match {NAME_RE.pattern}")
            continue
        if not isinstance(entry, dict):
            problems.append(f"api source: skipped {name}: must be an object")
            continue
        tabs, agent_id, account, settings = (entry.get(key) for key in ("tabs", "agent_id", "account", "settings"))
        if not (isinstance(tabs, str) and Path(tabs).expanduser().is_absolute()):
            problems.append(f"api source: skipped {name}: tabs must be an absolute path")
            continue
        if not (isinstance(agent_id, str) and agent_id in agent_ids):
            problems.append(f"api source: skipped {name}: agent_id {agent_id!r} is not in agents")
            continue
        if account is not None and not (isinstance(account, str) and NAME_RE.fullmatch(account)):
            problems.append(f"api source: skipped {name}: account must match {NAME_RE.pattern}")
            continue
        if settings is not None and not (isinstance(settings, str) and Path(settings).expanduser().is_absolute()):
            problems.append(f"api source: skipped {name}: settings must be an absolute path")
            continue
        account = account or DEFAULT_WALLET
        if account not in wallet_names:
            problems.append(f"api source: {name} names account {account}, which is not in api_accounts")
        declared.append(ApiTabSource(name=name, tabs=Path(tabs).expanduser(), agent_id=agent_id, account=account,
                                     settings=Path(settings).expanduser() if isinstance(settings, str) else None))
    return declared


def _source_tabs(declared: list[ApiTabSource], listed: ApiTabSources, taken: set[str],
                 problems: list[str]) -> list[ApiTab]:
    """The tabs the sources list now, in the order of the configuration, without the ids already taken."""
    tabs: list[ApiTab] = []
    for source in declared:
        for row in listed.rows(source.name):
            tab_id = f"{API_TAB_ID_PREFIX}{row.name}"
            if tab_id in taken:
                problems.append(f"api source: {source.name} row {row.name} skipped: the id {tab_id} is already a tab")
                continue
            taken.add(tab_id)
            tabs.append(ApiTab(id=tab_id, name=row.name, title=row.title, agent_id=source.agent_id,
                               account=source.account, record=row.record, source=source.name))
    return tabs


# The table now in force, with what it was built from: (configuration object, sources' identity version, table). One
# tuple, swapped whole, so a reader on another thread never pairs one table with another's key.
_loaded: tuple[dict[str, Any] | None, int, ApiTabTable] = (None, -1, ApiTabTable([], [], []))
_build_lock = threading.Lock()


def current_table() -> ApiTabTable:
    """The table now in force. Building it again (and writing what changed to the log) happens only when the
    configuration was read again or a source lists other tabs, so the call is cheap enough for every door. The doors
    run on the event loop and in worker threads; one lock makes one build per change."""
    global _loaded
    settings, version = config.get_config(), sources.identity_version
    built_from, built_version, table = _loaded
    if settings is built_from and version == built_version:
        return table
    with _build_lock:
        built_from, built_version, previous = _loaded
        if settings is built_from and version == built_version:
            return previous
        table = ApiTabTable.from_config(settings, sources)
        _loaded = (settings, version, table)
    _log_load(previous, table, problems_too=settings is not built_from)
    return table


def _log_load(previous: ApiTabTable, table: ApiTabTable, *, problems_too: bool) -> None:
    """Write what the new table changed: the problems (when the configuration was read again, or a source's row is
    left out), the wallets and sources (when the configuration was read again), and the tabs that came or went."""
    if problems_too:
        for account in table.accounts:
            logger.info("api account: loaded %s spend=%s", account.name, account.spend)
        for source in table.sources:
            logger.info("api source: loaded %s tabs=%s settings=%s", source.name, source.tabs, source.settings)
    for problem in table.problems:
        if problems_too or problem.startswith("api source: ") and problem not in previous.problems:
            logger.warning(problem)
    before = {tab.id: tab for tab in previous.tabs}
    for tab in table.tabs:
        if before.get(tab.id) != tab:
            logger.info("api tab: loaded %s record=%s exists=%s", tab.id, tab.record, tab.record.is_file())
    after = {tab.id for tab in table.tabs}
    for tab_id in [tab_id for tab_id in before if tab_id not in after]:
        logger.info("api tab: removed %s", tab_id)


def is_api_tab(tab_id: str) -> bool:
    """Whether `tab_id` is an API tab of the configuration now in force."""
    return tab_id.startswith(API_TAB_ID_PREFIX) and current_table().tab(tab_id) is not None
