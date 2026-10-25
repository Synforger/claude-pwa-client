"""Tier tabs: the backend places one tab per tier of an agent in the list. Started by `main.py`
(`tier_tabs_loop`) and called by `routes/tier_tabs.py` (`place_tab`, for `tabs open <tier>`).

An agent turns this on with `tier_tabs: true` in its configuration (it needs `launcher: true`, since only the
launcher reads the tier from the first message). Its tiers are read from its folder (`cwd`): `normal`, every
`projects/<P>` and every `projects/<P>/subprojects/<S>` (= folders whose name starts with `_` or `.` are not
tiers). Every `TICK_SEC` the backend places a tab for each tier that is not in the record yet (`record.py`).
A placed tab remembers its tier (`SessionDef.tier_tab`) and starts no claude: the first message sent to it
(by the operator, or a message from another tab) starts its claude in that tier (`terminal/first_message.py`).
A tier that already has a tab when it is first seen (= a tab the operator opened by hand) is recorded without
placing another one. A tab the operator closes is not placed again: `tabs open <tier>` does that.

The first look waits `SEED_DELAY_SEC` after the backend starts, so the tiers of the tabs already running are
known by then (= `tab_tier` learns them when the backend finds each tab's claude).
"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path

from backend._common.state import SessionDef, register_session, sessions_meta
from backend.terminal.tab_tier import tab_tier
from backend.terminal.tier import DEFAULT_TIER
from backend.tier_tabs import record
from backend.tier_tabs.envelope import tab_name

logger = logging.getLogger(__name__)

#: How often the agents' folders are looked at for new tiers
TICK_SEC = 60.0
#: The wait before the first look: the backend finds the running tabs' claude one by one at start (= 0.2 s
#: apart) and gives each up to 60 s, so 1.5 times that
SEED_DELAY_SEC = 90.0


def folder_tiers(folder: Path) -> list[str]:
    """The tiers of the agent whose folder is `folder` (= `normal` first, then each project and its subprojects)."""
    tiers = [DEFAULT_TIER]
    for project in _tier_folders(folder / "projects"):
        tiers.append(f"projects/{project.name}")
        tiers += [f"projects/{project.name}/subprojects/{sub.name}" for sub in _tier_folders(project / "subprojects")]
    return tiers


def enabled_agents() -> dict[str, dict]:
    """The agents that have `tier_tabs: true` and can be started from a first message (= `launcher` with a
    `launch_alias`, and a `cwd`)."""
    from backend._common.config import AGENTS  # noqa: PLC0415
    enabled = {}
    for agent_id, cfg in AGENTS.items():
        if not cfg.get("tier_tabs"):
            continue
        if not (cfg.get("launcher") and cfg.get("launch_alias") and cfg.get("cwd")):
            logger.warning("tier tabs: agent %s needs launcher, launch_alias and cwd; skipped", agent_id)
            continue
        enabled[agent_id] = cfg
    return enabled


def agent_for_folder(folder: Path) -> str | None:
    """The agent whose folder is `folder`, or None when none or several are. An agent other agents name as
    their `child_agent` does not count (= it shares the folder but opens child tabs only)."""
    from backend._common.config import AGENTS  # noqa: PLC0415
    children = {cfg.get("child_agent") for cfg in AGENTS.values()}
    target = folder.expanduser().resolve()
    found = [agent_id for agent_id, cfg in AGENTS.items()
             if agent_id not in children and cfg.get("cwd") and Path(cfg["cwd"]).expanduser().resolve() == target]
    return found[0] if len(found) == 1 else None


def tab_of(agent_id: str, tier: str) -> str | None:
    """The tab of `agent_id` already working in `tier` or placed for it (= not a child tab), or None."""
    return next((meta.id for meta in sessions_meta.values()
                 if meta.agent_id == agent_id and not meta.child and tab_tier(meta.id) == tier), None)


def place_tab(agent_id: str, tier: str) -> SessionDef:
    """Place a tab of `agent_id` for `tier` in the list (= no claude yet) and record the tier."""
    from backend._common.config import AGENTS  # noqa: PLC0415
    cfg = AGENTS[agent_id]
    meta = register_session(agent_id, tab_name(tier, cfg.get("display_name") or agent_id), tier_tab=tier)
    tiers = record.load()
    tiers.setdefault(agent_id, set()).add(tier)
    record.save(tiers)
    logger.info("tier tab placed agent=%s tier=%s session=%s", agent_id, tier, meta.id)
    return meta


def place_new_tiers() -> list[str]:
    """Place a tab for each tier of each enabled agent that is not in the record yet. → the tabs placed."""
    tiers = record.load()
    placed: list[str] = []
    for agent_id, cfg in enabled_agents().items():
        known = tiers.setdefault(agent_id, set())
        for tier in folder_tiers(Path(cfg["cwd"]).expanduser()):
            if tier in known:
                continue
            if tab_of(agent_id, tier) is None:
                placed.append(place_tab(agent_id, tier).id)
            known.add(tier)
            record.save(tiers)
    return placed


async def tier_tabs_loop(interval_sec: float = TICK_SEC, first_delay_sec: float = SEED_DELAY_SEC) -> None:
    """Look for new tiers every `interval_sec`, the first time after `first_delay_sec`."""
    logger.info("tier_tabs_loop started (interval=%ds, first look after %ds)", interval_sec, first_delay_sec)
    try:
        await asyncio.sleep(first_delay_sec)
        while True:
            try:
                place_new_tiers()
            except Exception:
                logger.exception("tier_tabs_loop iteration failed")
            await asyncio.sleep(interval_sec)
    except asyncio.CancelledError:
        logger.info("tier_tabs_loop cancelled")
        raise


def _tier_folders(parent: Path) -> list[Path]:
    """The folders under `parent` that are tiers (= not starting with `_` or `.`), by name."""
    if not parent.is_dir():
        return []
    return sorted((p for p in parent.iterdir() if p.is_dir() and not p.name.startswith(("_", "."))),
                  key=lambda p: p.name)
