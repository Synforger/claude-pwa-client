"""The account hold settings, read from the accounts of `config.json` (= `accounts.<account>.hold`).

    "accounts": {
      "personal": { "env": {...}, "hold": { "five_hour_at_pct": 95,
                                            "seven_day_at_pct": { "mon": 70, "sat": 100 } } }
    }

An account with a `hold` stops its tabs (the ones the operator did not pin to it) at a break while the usage of its 7
days is at the line of the day of the week or more, or the usage of its 5 hours is at `five_hour_at_pct` or more.
`seven_day_at_pct` gives the line of the 7 days for single days (`mon` to `sun`, each 1 to 100); a day it does not
name has no line. `five_hour_at_pct` (1 to 100) is the line of the 5 hours; without it the 5 hours never stop a tab.
Nothing continues the tabs by itself: the operator does, from the settings screen. A `hold` is used only when it is an
object that names `seven_day_at_pct` (a table of that form), `five_hour_at_pct` (a whole number of that range) or both,
and the account has no `fallback` (= an account either moves its tabs away or stops them). Any other `hold` is left
out and named in a warning at startup. Without a usable `hold` nothing is stopped.

Used by `hold_patrol.py`.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field

import backend._common.config as config
from backend.account_fallback.fallback_settings import AT_PCT_MAX, AT_PCT_MIN, is_pct, seven_day_problem

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class HoldRule:
    """One account's hold: the usage from which its tabs are stopped.

    seven_day_at_pct: the line of the 7 days on the days of the week it names (`WEEKDAYS` to a percentage)
    five_hour_at_pct: the line of the 5 hours, None when the 5 hours never stop a tab
    """
    account: str
    seven_day_at_pct: dict[str, int] = field(default_factory=dict)
    five_hour_at_pct: int | None = None


def _problem(account: dict) -> str | None:
    """Why the `hold` of an account (its settings entry) cannot be used, None when it can."""
    raw = account["hold"]
    if "fallback" in account:
        return "the account has a `fallback`, which moves its tabs away (an account either moves or stops them)"
    if not isinstance(raw, dict):
        return "it is not an object"
    if "seven_day_at_pct" not in raw and "five_hour_at_pct" not in raw:
        return "it names neither `seven_day_at_pct` nor `five_hour_at_pct`"
    if "five_hour_at_pct" in raw and not is_pct(raw["five_hour_at_pct"]):
        return f"`five_hour_at_pct` is not a whole number from {AT_PCT_MIN} to {AT_PCT_MAX}: {raw['five_hour_at_pct']!r}"
    return seven_day_problem(raw["seven_day_at_pct"]) if "seven_day_at_pct" in raw else None


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
        raw = account["hold"]
        rules[name] = HoldRule(account=name, seven_day_at_pct=dict(raw.get("seven_day_at_pct", {})),
                               five_hour_at_pct=raw.get("five_hour_at_pct"))
    return rules, tuple(problems)


def read_rules() -> dict[str, HoldRule]:
    """The usable holds of the client's configuration, by account."""
    return parse_rules(config.get_config().get("accounts"))[0]


def warn_unusable() -> None:
    """Say at startup, one line each, which `hold` of the configuration is left out and why."""
    for problem in parse_rules(config.get_config().get("accounts"))[1]:
        logger.warning("account hold: %s", problem)
