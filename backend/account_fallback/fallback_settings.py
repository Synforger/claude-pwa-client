"""The account fallback settings, read from the accounts of `config.json` (= `accounts.<account>.fallback`).

    "accounts": {
      "work":     { "env": {...}, "fallback": { "to": "personal", "at_pct": 95,
                                                "seven_day_at_pct": { "mon": 70, "sat": 100 } } },
      "personal": { "env": {...} }
    }

An account moves its tabs to `to` once the usage of its 5 hours or its 7 days is at `at_pct` or more (1 to 100), and
takes them back when that is over. `seven_day_at_pct` (optional) gives the line of the 7 days for single days of the
week (`mon` to `sun`, each 1 to 100); a day it does not name, and an account without it, use `at_pct`. A `fallback` is
used only when `to` is another account of the configuration, the account it names has no `fallback` of its own (= no
reverse direction, no chain), `at_pct` is a whole number from 1 to 100 and `seven_day_at_pct` is a table of that
form. Any other `fallback` is left out and named in a warning at startup. Without a usable `fallback` nothing moves.

Used by `fallback_patrol.py`.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field

import backend._common.config as config

logger = logging.getLogger(__name__)

AT_PCT_MIN = 1
AT_PCT_MAX = 100
# The names of the days of the week in the order `datetime.weekday()` counts them (Monday is 0).
WEEKDAYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")


@dataclass(frozen=True)
class FallbackRule:
    """One account's fallback: where its tabs go, and the usage (a percentage) from which they go.

    at_pct:           the line of the 5 hours, and of the 7 days on a day `seven_day_at_pct` does not name
    seven_day_at_pct: the line of the 7 days on the days of the week it names (`WEEKDAYS` to a percentage)
    """
    from_account: str
    to_account: str
    at_pct: int
    seven_day_at_pct: dict[str, int] = field(default_factory=dict)


def is_pct(value: object) -> bool:
    """Whether `value` is a line that can be set: a whole number from `AT_PCT_MIN` to `AT_PCT_MAX`."""
    return isinstance(value, int) and not isinstance(value, bool) and AT_PCT_MIN <= value <= AT_PCT_MAX


def seven_day_problem(table: object) -> str | None:
    """Why a `seven_day_at_pct` table (of a `fallback`, or of a `hold`) cannot be used, None when it can."""
    if not isinstance(table, dict):
        return f"`seven_day_at_pct` is not an object: {table!r}"
    for day, pct in table.items():
        if day not in WEEKDAYS:
            return f"`seven_day_at_pct` names {day!r}, which is not one of {', '.join(WEEKDAYS)}"
        if not is_pct(pct):
            return f"`seven_day_at_pct.{day}` is not a whole number from {AT_PCT_MIN} to {AT_PCT_MAX}: {pct!r}"
    return None


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
    if not is_pct(at_pct):
        return f"`at_pct` is not a whole number from {AT_PCT_MIN} to {AT_PCT_MAX}: {at_pct!r}"
    return seven_day_problem(raw["seven_day_at_pct"]) if "seven_day_at_pct" in raw else None


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
        rules[name] = FallbackRule(from_account=name, to_account=raw["to"], at_pct=raw["at_pct"],
                                   seven_day_at_pct=dict(raw.get("seven_day_at_pct", {})))
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
