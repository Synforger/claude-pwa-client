"""What the settings screen shows: the usage and the lines of each account, the tabs the account hold stopped, the tabs
pinned to an account, the sleep and rollover of each agent, the notification title, the child limit and the facts about
the machine that runs the backend. Reads the settings and the state; changes nothing.

Used by `routes/settings.py`.
"""
from __future__ import annotations

import re
import time
import tomllib
from pathlib import Path

import backend._common.config as config
from backend._common import state
from backend._common.paths import LOGS_DIR, REPO_ROOT
from backend.account_fallback import fallback_settings
from backend.account_fallback.fallback_judgement import seven_day_line_pct
from backend.account_fallback.fallback_settings import AT_PCT_MAX, AT_PCT_MIN, WEEKDAYS
from backend.account_hold import hold_settings
from backend.account_hold.hold_judgement import hold_line_pct, is_over_line
from backend.account_hold.hold_tabs import account_of, held_tabs
from backend.observability.loop_stall import STALL_FILE_NAME
from backend.settings.settings_fields import CONTEXT_PCT_MAX, CONTEXT_PCT_MIN, MINUTES_MIN
from backend.usage.usage import latest_from_tail, read_all_rate_limits_tail

# How much of the end of the stall log is read to find its last record.
STALL_TAIL_BYTES = 64 * 1024
_STALL_RECORD = re.compile(r"^--- the stacks above: loop stood still (\d+)s, back at (\S+) ---$", re.MULTILINE)


def _read_version() -> str | None:
    """The version of the code this process started with (= the one in `pyproject.toml` when it started)."""
    try:
        return tomllib.loads((REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]["version"]
    except (OSError, KeyError, ValueError):
        return None


# The version is read once, when the backend starts: the checkout may move on while this process does not.
RUNNING_VERSION = _read_version()


def last_loop_stall(log_dir: Path = LOGS_DIR) -> dict | None:
    """The last time the event loop stood still, from the stall log: when it was back and for how long it had stood. None
    when the log has no record (= the loop never stood still, or the log is gone)."""
    try:
        path = log_dir / STALL_FILE_NAME
        with path.open("rb") as fh:
            fh.seek(max(0, path.stat().st_size - STALL_TAIL_BYTES))
            tail = fh.read().decode("utf-8", errors="replace")
    except OSError:
        return None
    records = _STALL_RECORD.findall(tail)
    return {"stood_still_sec": int(records[-1][0]), "back_at": records[-1][1]} if records else None


def _usage_of(account: str, rows: list[dict]) -> dict | None:
    latest = latest_from_tail(rows, account_id=account)
    if not latest:
        return None
    return {key: latest.get(key) for key in ("five_hour_pct", "five_hour_resets_at", "seven_day_pct",
                                              "seven_day_resets_at")}


def _account_view(name: str, entry: object, rows: list[dict], now: float) -> dict:
    fallback = fallback_settings.read_rules().get(name)
    hold = hold_settings.read_rules().get(name)
    held = held_tabs(name)
    over_hold_line = is_over_line(rows, hold, now) if hold is not None else False
    return {
        "id": name,
        "display_name": fallback_settings.display_name_of(name),
        "is_default": name == config.default_account_id(),
        "usage": _usage_of(name, rows),
        # What the account does at its line: its tabs move to `fallback.to`, or are stopped (`hold`), or nothing.
        "mode": "fallback" if fallback is not None else "hold" if hold is not None else "none",
        "fallback": None if fallback is None else {
            "to": fallback.to_account, "to_display_name": fallback_settings.display_name_of(fallback.to_account),
            "at_pct": fallback.at_pct, "seven_day_at_pct": dict(fallback.seven_day_at_pct),
            "seven_day_today_pct": seven_day_line_pct(fallback, now)},
        "hold": None if hold is None else {"seven_day_at_pct": dict(hold.seven_day_at_pct),
                                           "today_pct": hold_line_pct(hold, now)},
        "held_count": len(held),
        # A stopped tab can be continued once the usage is under the line of today (= not known counts as under).
        "can_continue": bool(held) and over_hold_line is not True,
        "pinned_tabs": [{"id": meta.id, "title": meta.title} for meta in list(state.sessions_meta.values())
                        if meta.account_pinned and account_of(meta) == name],
    }


def _agent_view(agent_id: str, entry: object) -> dict:
    agent = entry if isinstance(entry, dict) else {}
    sleep = agent.get("sleep") if isinstance(agent.get("sleep"), dict) else {}
    rollover = agent.get("rollover") if isinstance(agent.get("rollover"), dict) else {}
    working = rollover.get("working") if isinstance(rollover.get("working"), dict) else {}
    idle = rollover.get("idle") if isinstance(rollover.get("idle"), dict) else {}
    return {
        "id": agent_id,
        "display_name": agent.get("display_name", agent_id.upper()),
        "sleep_minutes": sleep.get("minutes"),
        "rollover": {"working_context_pct": working.get("context_pct"), "idle_context_pct": idle.get("context_pct"),
                     "idle_minutes": idle.get("minutes")},
    }


def build_view(now: float | None = None) -> dict:
    """Everything the settings screen shows, from the settings now in force and the state now."""
    now = time.time() if now is None else now
    rows = read_all_rate_limits_tail()
    return {
        "accounts": [_account_view(name, entry, rows, now) for name, entry in config.ACCOUNTS.items()],
        "agents": [_agent_view(agent_id, entry) for agent_id, entry in config.AGENTS.items()],
        "child_sessions_max": config.CHILD_SESSIONS_MAX,
        "notification_title": config.NOTIFICATION_TITLE_DEFAULT,
        "machine": {"version": RUNNING_VERSION, "backend_started_at": state.backend_start_time,
                    "loop_stall": last_loop_stall()},
        "limits": {"weekdays": list(WEEKDAYS), "line_pct_min": AT_PCT_MIN, "line_pct_max": AT_PCT_MAX,
                   "context_pct_min": CONTEXT_PCT_MIN, "context_pct_max": CONTEXT_PCT_MAX, "minutes_min": MINUTES_MIN},
    }
