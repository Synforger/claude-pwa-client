"""The tier each tab's agent started in, read from the `AGENT_TIER` its claude process was given.

The agent's launcher decides a tier from the conversation's first message and hands it to claude as an
environment variable, so the backend reads the variable instead of deriving a tier of its own (see `tier`).
`pty_discover` records it when it finds the claude of a tab; the routes that list tabs or place a tab's memo
read what was recorded. Nothing here starts a process, so it is safe to call from the event loop.
"""

from __future__ import annotations

import logging

import psutil

from backend.terminal.tier import parse_tier

logger = logging.getLogger(__name__)

TIER_VARIABLE = "AGENT_TIER"

#: tab id → the tier its claude was started with (= `None` when the process was given none)
_tiers: dict[str, str | None] = {}


def read_tier(pid: int) -> str | None:
    """The tier of the process `pid` (= `None` when it is gone, not readable, or was given none)."""
    try:
        return parse_tier(psutil.Process(pid).environ().get(TIER_VARIABLE))
    except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess, OSError):
        return None


def set_tier(session_id: str, tier: str | None) -> bool:
    """Remember the tier a tab was started in. True when it differs from what was known."""
    changed = session_id not in _tiers or _tiers[session_id] != tier
    _tiers[session_id] = tier
    if changed:
        logger.info("tab tier session=%s tier=%s", session_id, tier)
    return changed


def record_tier(session_id: str, claude_pid: int) -> bool:
    """Remember the tier of the claude now running in a tab. True when it differs from what was known."""
    return set_tier(session_id, read_tier(claude_pid))


def tab_tier(session_id: str) -> str | None:
    """The tier a tab was started in, or `None` when it is not known (= no claude seen yet, or none was given)."""
    return _tiers.get(session_id)


def forget_tier(session_id: str) -> None:
    """Drop what is known about a tab that no longer exists."""
    _tiers.pop(session_id, None)
