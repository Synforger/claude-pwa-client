"""What a tier is, as pure functions: the tier a value names and the folder a tier points at.

A tier is the part of an agent's folder a conversation works in: `normal` for the folder itself,
`projects/<name>` for a folder below it. The agent's launcher decides it and hands it to claude as the
environment variable `AGENT_TIER`. Called by `tab_tier` (reads the variable) and `tab_memo` (places a memo).
"""

from __future__ import annotations

from pathlib import Path, PurePosixPath

#: The tier of a conversation that works in the agent's own folder
DEFAULT_TIER = "normal"


def parse_tier(value: str | None) -> str | None:
    """The tier `value` names, or `None` when it names none (= unset, empty, absolute, or leaving the folder)."""
    if not value:
        return None
    parts = PurePosixPath(value).parts
    if value.startswith("/") or not parts or ".." in parts:
        return None
    return "/".join(parts)


def tier_path(agent_folder: Path, tier: str | None) -> Path:
    """The folder a tier points at inside `agent_folder` (= the folder itself for `normal` and for an unknown tier)."""
    if tier is None or tier == DEFAULT_TIER:
        return agent_folder
    return agent_folder / tier
