"""The account fallback settings, read from the accounts of `config.json` (= `accounts.<account>.fallback`).

    "accounts": {
      "work":     { "env": {...}, "fallback": { "to": "personal", "at_pct": 95 } },
      "personal": { "env": {...} }
    }

An account moves its tabs to `to` once the usage of its 5 hours or its 7 days is at `at_pct` or more (1 to 100), and
takes them back when that is over. A `fallback` is used only when `to` is another account of the configuration, the
account it names has no `fallback` of its own (= no reverse direction, no chain) and `at_pct` is a whole number from
1 to 100. Any other `fallback` is left out and named in a warning at startup. Without a usable `fallback` nothing
moves.

Used by `fallback_patrol.py`.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass

import backend._common.config as config

logger = logging.getLogger(__name__)

AT_PCT_MIN = 1
AT_PCT_MAX = 100


@dataclass(frozen=True)
class FallbackRule:
    """One account's fallback: where its tabs go, and the usage (a percentage) from which they go."""
    from_account: str
    to_account: str
    at_pct: int


def _problem(name: str, raw: object, accounts: dict) -> str | None:
    """Why the `fallback` of account `name` cannot be used, None when it can."""
    if not isinstance(raw, dict):
        return "it is not an object"
    to = raw.get("to")
    if not isinstance(to, str) or to not in accounts:
        return f"`to` is not an account of the configuration: {to!r}"
    if to == name:
        return "`to` is the account itself"
    target = accounts[to]
    if isinstance(target, dict) and "fallback" in target:
        return f"the account `{to}` it moves to has a `fallback` of its own"
    at_pct = raw.get("at_pct")
    if isinstance(at_pct, bool) or not isinstance(at_pct, int) or not AT_PCT_MIN <= at_pct <= AT_PCT_MAX:
        return f"`at_pct` is not a whole number from {AT_PCT_MIN} to {AT_PCT_MAX}: {at_pct!r}"
    return None


def parse_rules(accounts: object) -> tuple[dict[str, FallbackRule], tuple[str, ...]]:
    """The usable fallbacks of `accounts` by account, and one line for each `fallback` that cannot be used."""
    if not isinstance(accounts, dict):
        return {}, ()
    rules: dict[str, FallbackRule] = {}
    problems: list[str] = []
    for name, account in accounts.items():
        if not isinstance(account, dict) or "fallback" not in account:
            continue
        if (problem := _problem(name, account["fallback"], accounts)) is not None:
            problems.append(f"accounts.{name}.fallback is ignored: {problem}")
            continue
        raw = account["fallback"]
        rules[name] = FallbackRule(from_account=name, to_account=raw["to"], at_pct=raw["at_pct"])
    return rules, tuple(problems)


def read_rules() -> dict[str, FallbackRule]:
    """The usable fallbacks of the client's configuration, by the account they move tabs away from."""
    return parse_rules(config.get_config().get("accounts"))[0]


def warn_unusable() -> None:
    """Say at startup, one line each, which `fallback` of the configuration is left out and why."""
    for problem in parse_rules(config.get_config().get("accounts"))[1]:
        logger.warning("account fallback: %s", problem)


def display_name_of(account: str) -> str:
    """The name the operator knows the account by (= `accounts.<account>.display_name`), the account's key without one."""
    accounts = config.get_config().get("accounts")
    entry = accounts.get(account) if isinstance(accounts, dict) else None
    name = entry.get("display_name") if isinstance(entry, dict) else None
    return name if isinstance(name, str) and name else account
