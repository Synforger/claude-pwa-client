"""The tier each tab's agent started in, read from the `AGENT_TIER` its claude process was given.

The agent's launcher decides a tier from the conversation's first message and hands it to claude as an
environment variable, so the backend reads the variable instead of deriving a tier of its own (see `tier`).
`pty_discover` records it when it finds the claude of a tab; the routes that list tabs or place a tab's memo
read what was recorded. What is recorded is stored with the tab (`SessionDef.tier`), so a tab keeps its tier while
no claude runs in it, as after a restart of the backend or the machine. A tier tab whose claude has not started yet
answers with the tier it was placed for. Nothing here starts a process, so it is safe to call from the event loop.
"""

from __future__ import annotations

import logging

import psutil

from backend.terminal.tier import parse_tier

logger = logging.getLogger(__name__)

TIER_VARIABLE = "AGENT_TIER"


def read_tier(pid: int) -> str | None:
    """The tier of the process `pid` (= `None` when it is gone, not readable, or was given none)."""
    try:
        return parse_tier(psutil.Process(pid).environ().get(TIER_VARIABLE))
    except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess, OSError):
        return None


def set_tier(session_id: str, tier: str | None) -> bool:
    """Store the tier a tab was started in. True when it differs from what was known."""
    from backend._common import state  # noqa: PLC0415
    meta = state.sessions_meta.get(session_id)
    if meta is None or meta.tier == tier:
        return False
    meta.tier = tier
    state.save_sessions_meta()
    logger.info("tab tier session=%s tier=%s", session_id, tier)
    return True


def record_tier(session_id: str, claude_pid: int) -> bool:
    """Store the tier of the claude now running in a tab. True when it differs from what was known. A process that
    names no tier leaves what is known: it may simply be gone by now, and a tab does not change tier by that."""
    tier = read_tier(claude_pid)
    return tier is not None and set_tier(session_id, tier)


def tab_tier(session_id: str) -> str | None:
    """The tier a tab works in: the one its claude was last started in, else the one it was placed for as a tier tab
    (= `SessionDef.tier_tab`), else `None` (= no claude seen yet, or none was given)."""
    from backend._common.state import sessions_meta  # noqa: PLC0415
    meta = sessions_meta.get(session_id)
    if meta is None:
        return None
    return meta.tier if meta.tier is not None else meta.tier_tab
