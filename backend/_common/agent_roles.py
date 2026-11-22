"""What an agent of the configuration is for, judged from the configuration alone.

Read by the agents view (`routes/accounts.py`) and the tabs of tiers (`tier_tabs/tier_tabs.py`).
"""
from __future__ import annotations

from collections.abc import Mapping


def child_agent_ids(agents: Mapping[str, dict]) -> set[str]:
    """The agents another agent names as its `child_agent`. An agent that names itself is not one of them."""
    return {cfg["child_agent"] for name, cfg in agents.items() if cfg.get("child_agent") not in (None, "", name)}


def is_offered_for_new_tab(name: str, cfg: dict, child_ids: set[str]) -> bool:
    """Whether a person starts conversations with the agent: not one for child tabs, and not one a program asks."""
    return name not in child_ids and cfg.get("ask") is not True
