"""What `GET /capacity` answers: how much this machine holds now and how much room is left, as plain numbers. No line
and no limit is decided here: the only limit is the operator's `child_sessions_max`, given as it is (None = none). The
one derived number is how many more claudes of the median footprint the available memory holds.

Used by `routes/capacity.py` with what `capacity_sensors.py` read.
"""
from __future__ import annotations

import statistics

from backend.capacity.capacity_sensors import MemoryNow, TabFacts


def build_view(*, machine: str, child_sessions_max: int | None, caller: str | None, tabs: list[TabFacts],
               memory: MemoryNow, usage: dict[str, dict | None]) -> dict:
    """The answer of `GET /capacity`. `caller` is the tab that asks (= its children are counted), or None."""
    footprints = [tab.claude_mb for tab in tabs if tab.claude_mb is not None]
    median_mb = statistics.median(footprints) if footprints else None
    return {
        "machine": machine,
        "child_sessions_max": child_sessions_max,
        "children_of_caller": None if caller is None else sum(1 for tab in tabs if tab.child and tab.parent_id == caller),
        "tabs": {
            "total": len(tabs),
            "with_claude": sum(1 for tab in tabs if tab.has_claude),
            # a tab being put to sleep or woken has the mark and a running claude: it counts as running, so the three add up
            "asleep": sum(1 for tab in tabs if tab.asleep and not tab.has_claude),
            "without_claude": sum(1 for tab in tabs if not tab.has_claude and not tab.asleep),
            "children": sum(1 for tab in tabs if tab.child),
        },
        "claude_mb": None if not footprints else {
            "count": len(footprints), "median": round(median_mb, 1), "min": round(min(footprints), 1),
            "max": round(max(footprints), 1), "total": round(sum(footprints), 1)},
        "memory": {"total_mb": round(memory.total_mb, 1), "available_mb": round(memory.available_mb, 1),
                   "pressure_level": memory.level, "swap_used_mb": round(memory.swap_used_mb, 1)},
        "claudes_fitting_available": None if not median_mb else int(memory.available_mb // median_mb),
        "accounts": [{"id": account, "usage": account_usage,
                      "tabs_with_claude": sum(1 for tab in tabs if tab.has_claude and tab.account == account)}
                     for account, account_usage in usage.items()],
    }
