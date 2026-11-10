"""The sleep settings of an agent, read from its entry in `config.json` (= `agents.<id>.sleep`).

    "sleep": { "minutes": 60, "pressure_minutes": 10 }

An agent without the entry (or with a value that is not a whole number of minutes, 1 or more) never has its tabs
put to sleep. `pressure_minutes` (a whole number from 1 to `minutes`) is how long a tab must be quiet to be put to
sleep while the machine is short of memory; without it, or out of that range, the agent's tabs are not put to sleep
earlier. Used by the sleep patrol (`sleep_patrol.py`) and the sensors (`sleep_sensors.py`).
"""
from __future__ import annotations

from backend.terminal.session_resolver import resolve_agent_cfg


def sleep_minutes(session_id: str) -> int | None:
    """After how many quiet minutes the tab's claude is put to sleep; None when the tab's agent does not sleep."""
    return _whole_minutes(_section(session_id).get("minutes"))


def pressure_minutes(session_id: str) -> int | None:
    """After how many quiet minutes the tab's claude may be put to sleep while the machine is short of memory; None
    when the agent does not sleep, sets no such value, or sets one above its `minutes`."""
    minutes = sleep_minutes(session_id)
    pressure = _whole_minutes(_section(session_id).get("pressure_minutes"))
    return pressure if minutes is not None and pressure is not None and pressure <= minutes else None


def _section(session_id: str) -> dict:
    section = (resolve_agent_cfg(session_id) or {}).get("sleep")
    return section if isinstance(section, dict) else {}


def _whole_minutes(value: object) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) and value >= 1 else None


def rollover_idle_pct(session_id: str) -> float | None:
    """The context percentage above which the automatic rollover takes a quiet tab over (= `rollover.idle.context_pct`);
    None when the agent has no such line. A tab below the line is the sleep's, a tab above it the rollover's."""
    rollover = (resolve_agent_cfg(session_id) or {}).get("rollover")
    idle = rollover.get("idle") if isinstance(rollover, dict) else None
    pct = idle.get("context_pct") if isinstance(idle, dict) else None
    return pct if isinstance(pct, (int, float)) and not isinstance(pct, bool) else None
