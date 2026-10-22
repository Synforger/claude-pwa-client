"""A tab's top page (= `<tier folder>/pages/<tab id>/index.html`, next to the memo).

The backend makes it from the agent's template when a tab's tier is recorded, and the 📋 screen links to it.
A page that exists is never touched: the tab's agent and the operator own what is written in it. Called by
`pty_discover` (once the tier of a tab is known) and by the memo routes (to tell the screen the page).
"""

from __future__ import annotations

import logging
from pathlib import Path

from backend._common import state
from backend._common.state import atomic_write_text
from backend.terminal.page_template import fill_template, template_file
from backend.terminal.tab_memo import agent_folder, page_path
from backend.terminal.tab_tier import tab_tier

logger = logging.getLogger(__name__)


def existing_page(session_id: str) -> Path | None:
    """The top page of a tab, or `None` when it has none yet."""
    path = page_path(session_id)
    return path if path.is_file() else None


def make_page(session_id: str) -> Path | None:
    """Make the top page of a tab from its agent's template, when the tab's tier is known, the page does not
    exist yet and the agent has a template. Returns the page that was made, or `None` when nothing was made."""
    tier = tab_tier(session_id)
    meta = state.sessions_meta.get(session_id)
    if tier is None or meta is None:
        return None
    page = page_path(session_id)
    template = template_file(agent_folder(session_id))
    if page.exists() or not template.is_file():
        return None
    try:
        text = fill_template(template.read_text(encoding="utf-8"), title=meta.title, tier=tier)
        page.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_text(page, text)
    except (OSError, UnicodeDecodeError):
        logger.exception("failed to make the top page of tab %s from %s", session_id, template)
        return None
    logger.info("tab page made session=%s path=%s", session_id, page)
    return page
