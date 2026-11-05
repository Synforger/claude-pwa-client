"""The sleep settings of an agent, read from its entry in `config.json` (= `agents.<id>.sleep`).

    "sleep": { "minutes": 60 }

An agent without the entry (or with a value that is not a whole number of minutes, 1 or more) never has its tabs
put to sleep. Used by the sleep patrol (`sleep_patrol.py`) and the sensors (`sleep_sensors.py`).
"""
from __future__ import annotations

from backend.terminal.session_resolver import resolve_agent_cfg


def sleep_minutes(session_id: str) -> int | None:
    """After how many quiet minutes the tab's claude is put to sleep; None when the tab's agent does not sleep."""
    section = (resolve_agent_cfg(session_id) or {}).get("sleep")
    minutes = section.get("minutes") if isinstance(section, dict) else None
    return minutes if isinstance(minutes, int) and not isinstance(minutes, bool) and minutes >= 1 else None


def rollover_idle_pct(session_id: str) -> float | None:
    """The context percentage above which the automatic rollover takes a quiet tab over (= `rollover.idle.context_pct`);
    None when the agent has no such line. A tab below the line is the sleep's, a tab above it the rollover's."""
    rollover = (resolve_agent_cfg(session_id) or {}).get("rollover")
    idle = rollover.get("idle") if isinstance(rollover, dict) else None
    pct = idle.get("context_pct") if isinstance(idle, dict) else None
    return pct if isinstance(pct, (int, float)) and not isinstance(pct, bool) else None
