"""The account hold settings, read from the accounts of `config.json` (= `accounts.<account>.hold`).

    "accounts": {
      "personal": { "env": {...}, "hold": { "seven_day_at_pct": { "mon": 70, "sat": 100 } } }
    }

An account with a `hold` stops its tabs (the ones the operator did not pin to it) at a break while the usage of its 7
days is at the line of the day of the week or more. `seven_day_at_pct` gives the line for single days (`mon` to `sun`,
each 1 to 100); a day it does not name has no line. Nothing continues the tabs by itself: the operator does, from
the settings screen. A `hold` is used only when it is an object whose `seven_day_at_pct` is a table of that form and
the account has no `fallback` (= an account either moves its tabs away or stops them). Any other `hold` is left out and
named in a warning at startup. Without a usable `hold` nothing is stopped.

Used by `hold_patrol.py`.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field

import backend._common.config as config
from backend.account_fallback.fallback_settings import seven_day_problem

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class HoldRule:
    """One account's hold: the usage (a percentage of the 7 days) from which its tabs are stopped, by day of the week.

    seven_day_at_pct: the line of the days of the week it names (`WEEKDAYS` to a percentage)
    """
    account: str
    seven_day_at_pct: dict[str, int] = field(default_factory=dict)


def _problem(account: dict) -> str | None:
    """Why the `hold` of an account (its settings entry) cannot be used, None when it can."""
    raw = account["hold"]
    if "fallback" in account:
        return "the account has a `fallback`, which moves its tabs away (an account either moves or stops them)"
    if not isinstance(raw, dict):
        return "it is not an object"
    if "seven_day_at_pct" not in raw:
        return "`seven_day_at_pct` is missing"
    return seven_day_problem(raw["seven_day_at_pct"])


def parse_rules(accounts: object) -> tuple[dict[str, HoldRule], tuple[str, ...]]:
    """The usable holds of `accounts` by account, and one line for each `hold` that cannot be used."""
    if not isinstance(accounts, dict):
        return {}, ()
    rules: dict[str, HoldRule] = {}
    problems: list[str] = []
    for name, account in accounts.items():
        if not isinstance(account, dict) or "hold" not in account:
            continue
        if (problem := _problem(account)) is not None:
            problems.append(f"accounts.{name}.hold is ignored: {problem}")
            continue
        rules[name] = HoldRule(account=name, seven_day_at_pct=dict(account["hold"]["seven_day_at_pct"]))
    return rules, tuple(problems)


def read_rules() -> dict[str, HoldRule]:
    """The usable holds of the client's configuration, by account."""
    return parse_rules(config.get_config().get("accounts"))[0]


def warn_unusable() -> None:
    """Say at startup, one line each, which `hold` of the configuration is left out and why."""
    for problem in parse_rules(config.get_config().get("accounts"))[1]:
        logger.warning("account hold: %s", problem)
