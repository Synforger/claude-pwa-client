"""Clearing what the client wrote for a child tab that is closed (= `<tier folder>/pages/<child id>/`).

A child tab is opened to hand one piece of work over, and closing it ends that work. What the client wrote for it goes
with it: its memo, its top page while it is still the template the client filled, and the folder once it is empty.
A page the child wrote itself stays, as every explanation page does. Called by `routes/sessions.py` when a child is
closed. The child's tier folder and its parent's are both looked at: `tabs new` writes the memo in the parent's tier,
and a child that started in another tier has its top page there.
"""

from __future__ import annotations

import logging
from pathlib import Path

from backend._common import state
from backend.terminal.page_template import fill_template, template_file
from backend.terminal.tab_memo import MEMO_NAME, PAGE_NAME, agent_folder, memo_file, tier_folder
from backend.terminal.tab_tier import tab_tier
from backend.terminal.tier import DEFAULT_TIER

logger = logging.getLogger(__name__)


def clear_child_folder(session_id: str) -> list[Path]:
    """Remove what the client wrote for the child tab `session_id`, before the tab itself is forgotten. Returns the
    files and folders that were removed. A tab that is not a child is left alone (= its memo stays with the agent)."""
    meta = state.sessions_meta.get(session_id)
    if meta is None or not meta.child:
        return []
    tab_ids = [session_id, *([meta.parent_id] if meta.parent_id in state.sessions_meta else [])]
    folders = {memo_file(tier_folder(tab_id), session_id).parent for tab_id in tab_ids}
    tiers = {tier for tier in (*(tab_tier(tab_id) for tab_id in tab_ids), DEFAULT_TIER) if tier}
    template = template_file(agent_folder(session_id))
    filled = _filled_pages(template, meta.title, tiers)
    removed: list[Path] = []
    for folder in sorted(folders):
        removed += _clear(folder, filled)
    if removed:
        logger.info("child tab folder cleared session=%s removed=%s", session_id, [str(path) for path in removed])
    return removed


def _filled_pages(template: Path, title: str, tiers: set[str]) -> set[str]:
    """Every top page the client could have made for the tab (= the template filled with each tier it may have had)."""
    try:
        text = template.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return set()
    return {fill_template(text, title=title, tier=tier) for tier in tiers}


def _clear(folder: Path, filled: set[str]) -> list[Path]:
    """Remove the memo and an untouched top page from `folder`, and the folder when nothing else is left in it."""
    removed: list[Path] = []
    memo, page = folder / MEMO_NAME, folder / PAGE_NAME
    try:
        if memo.is_file():
            memo.unlink()
            removed.append(memo)
        if page.is_file() and page.read_text(encoding="utf-8") in filled:
            page.unlink()
            removed.append(page)
        if folder.is_dir() and not any(folder.iterdir()):
            folder.rmdir()
            removed.append(folder)
    except (OSError, UnicodeDecodeError):
        logger.exception("could not clear the folder of a closed child tab: %s", folder)
    return removed
