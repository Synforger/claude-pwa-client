"""Which fields of `config.json` the settings screen may change, and what each may be set to. Pure: it takes the settings
as they are and a partial update, and answers with the settings after it, or with why it cannot be applied. It reads no
file and does not touch what it is given.

A partial update has the shape of `config.json` and names only what changes:

    {"accounts": {"personal": {"hold": {"five_hour_at_pct": 95, "seven_day_at_pct": {"mon": 70, "tue": null}}}},
     "agents": {"agent_a": {"sleep": {"minutes": 30}}},
     "child_sessions_max": 4}

A field is set to a value, or removed with `null` (= a day of the week without a line, no line of the 5 hours for a
`hold`, no width ahead of the line for a `fallback`, an agent that does not sleep, the default of `child_sessions_max`
and `notification_title`). Every field outside `FIELDS` is refused, and so is a value
that the readers of the field (`fallback_settings`, `hold_settings`, the sleep and the rollover) would not use. The
settings after the update must not have a problem the ones before did not have: a `fallback` or `hold` that was
already unusable does not stop another account's line from being changed.

Used by `settings_store.py`.
"""
from __future__ import annotations

import copy
from typing import Any, Iterator

from backend.account_fallback import fallback_settings
from backend.account_fallback.fallback_settings import WEEKDAYS, is_ahead_pct, is_pct
from backend.account_hold import hold_settings

# The numbers the rollover's fields take: the percentage of the context (1 to 100) and the minutes a tab must be quiet.
CONTEXT_PCT_MIN, CONTEXT_PCT_MAX = 1, 100
MINUTES_MIN = 1

# What can be changed, as the path in `config.json` (`*` = the id of an account or an agent). Shown to the operator
# by the screen; the readers of `FIELDS` below are the truth.
CHANGEABLE_PATHS = (
    "accounts.*.fallback.at_pct",
    "accounts.*.fallback.ahead_pct",
    "accounts.*.fallback.seven_day_at_pct.<day>",
    "accounts.*.hold.five_hour_at_pct",
    "accounts.*.hold.seven_day_at_pct.<day>",
    "agents.*.sleep.minutes",
    "agents.*.rollover.working.context_pct",
    "agents.*.rollover.idle.context_pct",
    "agents.*.rollover.idle.minutes",
    "child_sessions_max",
    "notification_title",
)

Path = tuple[str, ...]


class Rejected(Exception):
    """A partial update that cannot be applied. `reasons` says why, one line each."""

    def __init__(self, reasons: list[str]) -> None:
        super().__init__("; ".join(reasons))
        self.reasons = reasons


def _is_whole(value: object, minimum: int) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= minimum


def _is_number(value: object, minimum: float, maximum: float | None = None) -> bool:
    return (isinstance(value, (int, float)) and not isinstance(value, bool) and value >= minimum
            and (maximum is None or value <= maximum))


def _problem_of(path: Path, value: object) -> str | None:
    """Why `value` cannot be the value of the field at `path` (which is a field of `FIELDS`), None when it can."""
    kind = _kind_of(path)
    if kind == "line":
        return None if is_pct(value) else f"a whole number from {fallback_settings.AT_PCT_MIN} to {fallback_settings.AT_PCT_MAX}"
    if kind == "ahead":
        return None if is_ahead_pct(value) else \
            f"a whole number from {fallback_settings.AHEAD_PCT_MIN} to {fallback_settings.AHEAD_PCT_MAX}"
    if kind == "sleep_minutes":
        return None if _is_whole(value, MINUTES_MIN) else f"a whole number of {MINUTES_MIN} or more"
    if kind == "context_pct":
        return None if _is_number(value, CONTEXT_PCT_MIN, CONTEXT_PCT_MAX) else \
            f"a number from {CONTEXT_PCT_MIN} to {CONTEXT_PCT_MAX}"
    if kind == "minutes":
        return None if _is_number(value, MINUTES_MIN) else f"a number of {MINUTES_MIN} or more"
    if kind == "count":
        return None if _is_whole(value, 0) else "a whole number of 0 or more"
    return None if isinstance(value, str) and value.strip() else "a text that is not empty"


def _kind_of(path: Path) -> str | None:
    """What kind of field `path` is, None when it is not one the screen may change."""
    match path:
        case ("accounts", _, "fallback", "at_pct") | ("accounts", _, "hold", "five_hour_at_pct"):
            return "line"
        case ("accounts", _, "fallback", "ahead_pct"):
            return "ahead"
        case ("accounts", _, "fallback" | "hold", "seven_day_at_pct", day) if day in WEEKDAYS:
            return "line"
        case ("agents", _, "sleep", "minutes"):
            return "sleep_minutes"
        case ("agents", _, "rollover", "working" | "idle", "context_pct"):
            return "context_pct"
        case ("agents", _, "rollover", "idle", "minutes"):
            return "minutes"
        case ("child_sessions_max",):
            return "count"
        case ("notification_title",):
            return "text"
    return None


def _is_required(path: Path) -> bool:
    """Whether the field cannot be left out: setting `null` removes a field, and the line of the 5 hours of a `fallback`
    has no default to fall back to."""
    return path[0] == "accounts" and path[2:] == ("fallback", "at_pct")


def _leaves(update: dict, prefix: Path = ()) -> Iterator[tuple[Path, object]]:
    for key, value in update.items():
        if isinstance(value, dict):
            yield from _leaves(value, (*prefix, str(key)))
        else:
            yield (*prefix, str(key)), value


def _name(path: Path) -> str:
    return ".".join(path)


def _unknown_owner(path: Path, settings: dict) -> str | None:
    """Why the account or agent a field belongs to cannot take it (not in the settings, no `fallback` to change), None
    when it can."""
    if path[0] in ("accounts", "agents"):
        owners = settings.get(path[0])
        if not isinstance(owners, dict) or path[1] not in owners or not isinstance(owners[path[1]], dict):
            return f"{_name(path)}: there is no {path[0][:-1]} {path[1]!r}"
        if path[2:3] == ("fallback",) and not isinstance(owners[path[1]].get("fallback"), dict):
            return f"{_name(path)}: the account {path[1]!r} has no `fallback` (its target is not a field the screen sets)"
    return None


def _write(settings: dict, path: Path, value: object) -> None:
    node = settings
    for key in path[:-1]:
        node = node.setdefault(key, {})
    if value is None:
        node.pop(path[-1], None)
    else:
        node[path[-1]] = value


def _problems(settings: dict) -> list[str]:
    accounts = settings.get("accounts")
    return [*fallback_settings.parse_rules(accounts)[1], *hold_settings.parse_rules(accounts)[1]]


def apply_update(settings: dict[str, Any], update: object) -> tuple[dict[str, Any], list[str]]:
    """The settings after `update`, and the paths it changed (= the fields it named). Raises `Rejected` when any field
    of it is not allowed or any value cannot be used; then nothing of it is applied."""
    if not isinstance(update, dict) or not update:
        raise Rejected(["the update must be an object that names at least one field"])
    reasons: list[str] = []
    changes: list[tuple[Path, object]] = []
    for path, value in _leaves(update):
        if _kind_of(path) is None:
            reasons.append(f"{_name(path)}: this field cannot be changed here (changeable: {', '.join(CHANGEABLE_PATHS)})")
        elif (owner := _unknown_owner(path, settings)) is not None:
            reasons.append(owner)
        elif value is None and _is_required(path):
            reasons.append(f"{_name(path)}: it cannot be removed")
        elif value is not None and (problem := _problem_of(path, value)) is not None:
            reasons.append(f"{_name(path)}: must be {problem}, got {value!r}")
        else:
            changes.append((path, value))
    if reasons:
        raise Rejected(reasons)
    updated = copy.deepcopy(settings)
    for path, value in changes:
        _write(updated, path, value)
    before = _problems(settings)
    if introduced := [problem for problem in _problems(updated) if problem not in before]:
        raise Rejected(introduced)
    return updated, [_name(path) for path, _ in changes]

