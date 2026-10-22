"""Where a tab's memo (= the 📋 file) lives: `<tier folder>/pages/<tab id>/memo.md`.

The tier folder is the agent's folder with the tab's tier added (see `tier`; a tab whose tier is not known
is placed like `normal`). The same folder holds the tab's other pages, so a tab's memo and its top page sit
side by side. Called by `runner` (to tell the tab's agent where the memo is), by the memo routes, and by
the move of the memos an earlier version kept elsewhere (`memo_migration`).
"""

from __future__ import annotations

from pathlib import Path

import backend.config as _config
from backend import state
from backend.terminal.tab_tier import tab_tier
from backend.terminal.tier import tier_path

PAGES_FOLDER = "pages"
MEMO_NAME = "memo.md"


def memo_file(tier_folder: Path, session_id: str) -> Path:
    """The memo of tab `session_id` inside `tier_folder`. The id must be one the backend issued (= an id with a
    separator would point outside the folder)."""
    if not session_id or Path(session_id).name != session_id:
        raise ValueError(f"not a session id: {session_id!r}")
    return tier_folder / PAGES_FOLDER / session_id / MEMO_NAME


def agent_folder(session_id: str) -> Path:
    """The folder of the agent a tab runs (= its `cwd` in the config; the home folder when the config names none)."""
    meta = state.sessions_meta.get(session_id)
    if meta is None:
        raise ValueError(f"unknown session: {session_id!r}")
    cwd = (_config.AGENTS.get(meta.agent_id) or {}).get("cwd")
    return Path(cwd).expanduser() if cwd else Path.home()


def tier_folder(session_id: str) -> Path:
    """The folder of the tier a tab works in (= the agent's folder when the tier is not known or has no folder)."""
    folder = agent_folder(session_id)
    below = tier_path(folder, tab_tier(session_id))
    return below if below.is_dir() else folder


def memo_path(session_id: str) -> Path:
    """The memo file of a tab."""
    return memo_file(tier_folder(session_id), session_id)

