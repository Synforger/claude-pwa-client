"""Clearing what the client wrote for tabs that come from another tab (= `<tier folder>/pages/<tab id>/` of a child or
a fork).

A child tab is opened to hand one piece of work over, and closing it ends that work. What the client wrote for it goes
with it: its memo, its top page while it is still the template the client filled, and the folder once it is empty.
Such tabs get no top page any more (`terminal/tab_page.py`); the ones an earlier version gave them are cleared at the
backend's start, for every child and fork still listed, while they are untouched and the folder holds nothing but the
memo besides (`clear_derived_pages`; a folder with pages of the tab's own keeps the top page that leads to them). A
fork keeps its memo there, as an ordinary tab does.

A top page counts as untouched when it matches what the client wrote for the tab (= the fingerprint kept in
`SessionDef.top_page_sha`), or, for a tab that has none or whose page does not match it, the template as it is now
filled in. Lines that only load a script are ignored in both (= a tool adds a shared part, such as a contents bar, to
every page of the tier). A page the tab wrote itself stays, as every explanation page does. Called by
`routes/sessions.py` when a child is closed and by `main` at start. The tab's tier folder and its parent's are both
looked at: `tabs new` writes the memo in the parent's tier, and a tab that started in another tier has its top page there.
"""

from __future__ import annotations

import logging
from pathlib import Path

from backend._common import state
from backend.terminal.page_template import fill_template, page_fingerprint, pages_root_from, template_file
from backend.terminal.tab_memo import MEMO_NAME, PAGE_NAME, agent_folder, memo_file, page_file, tier_folder
from backend.terminal.tab_tier import tab_tier
from backend.terminal.tier import DEFAULT_TIER, tier_path

logger = logging.getLogger(__name__)


def clear_child_folder(session_id: str) -> list[Path]:
    """Remove what the client wrote for the child tab `session_id`, before the tab itself is forgotten. Returns the
    files and folders that were removed. A tab that is not a child is left alone (= its memo stays with the agent)."""
    meta = state.sessions_meta.get(session_id)
    if meta is None or not meta.child:
        return []
    removed: list[Path] = []
    for folder in _folders(session_id):
        removed += _clear(folder, _untouched(session_id), memo=True)
    if removed:
        logger.info("child tab folder cleared session=%s removed=%s", session_id, [str(path) for path in removed])
    return removed


def clear_derived_pages() -> list[Path]:
    """Remove the untouched top page of every child and fork tab still listed whose folder holds nothing but that page
    and the memo, and the folder once that leaves it empty (= the pages an earlier version made for them). Memos and
    folders with pages of the tab's own stay. Returns what was removed."""
    removed: list[Path] = []
    for session_id, meta in list(state.sessions_meta.items()):
        if meta.parent_id is None:
            continue
        for folder in _folders(session_id):
            if _holds_only_client_files(folder):
                removed += _clear(folder, _untouched(session_id), memo=False)
    if removed:
        logger.info("top pages of child and fork tabs cleared removed=%s", [str(path) for path in removed])
    return removed


def _folders(session_id: str) -> set[Path]:
    """The page folders of tab `session_id` in its own tier folder and in its parent's."""
    meta = state.sessions_meta[session_id]
    tab_ids = [session_id, *([meta.parent_id] if meta.parent_id in state.sessions_meta else [])]
    return {memo_file(tier_folder(tab_id), session_id).parent for tab_id in tab_ids}


def _holds_only_client_files(folder: Path) -> bool:
    """`folder` exists and holds no file but the memo and the top page (= nothing the tab wrote besides)."""
    try:
        return folder.is_dir() and {path.name for path in folder.iterdir()} <= {MEMO_NAME, PAGE_NAME}
    except OSError:
        return False


def _untouched(session_id: str) -> set[str]:
    """The fingerprints of every top page the client could have written for tab `session_id`."""
    meta = state.sessions_meta[session_id]
    tab_ids = [session_id, *([meta.parent_id] if meta.parent_id in state.sessions_meta else [])]
    tiers = {tier for tier in (*(tab_tier(tab_id) for tab_id in tab_ids), DEFAULT_TIER) if tier}
    untouched = _filled_fingerprints(agent_folder(session_id), session_id, meta.title, tiers)
    if meta.top_page_sha:
        untouched.add(meta.top_page_sha)
    return untouched


def _filled_fingerprints(agent: Path, session_id: str, title: str, tiers: set[str]) -> set[str]:
    """The fingerprint of every top page the client could make for the tab from the template as it is now (= the
    template filled with each tier the tab may have had, and the way up from that tier's page folder)."""
    try:
        text = template_file(agent).read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return set()
    fingerprints: set[str] = set()
    for tier in tiers:
        below = tier_path(agent, tier)
        page_folder = page_file(below if below.is_dir() else agent, session_id).parent
        filled = fill_template(text, title=title, tier=tier, pages_root=pages_root_from(agent, page_folder))
        fingerprints.add(page_fingerprint(filled))
    return fingerprints


def _clear(folder: Path, untouched: set[str], *, memo: bool) -> list[Path]:
    """Remove a top page whose fingerprint is in `untouched` from `folder` (and the memo too when `memo`), and the
    folder when nothing else is left in it."""
    removed: list[Path] = []
    memo_path, page = folder / MEMO_NAME, folder / PAGE_NAME
    try:
        if memo and memo_path.is_file():
            memo_path.unlink()
            removed.append(memo_path)
        if page.is_file() and page_fingerprint(page.read_text(encoding="utf-8")) in untouched:
            page.unlink()
            removed.append(page)
        if folder.is_dir() and not any(folder.iterdir()):
            folder.rmdir()
            removed.append(folder)
    except (OSError, UnicodeDecodeError):
        logger.exception("could not clear the folder of a child or fork tab: %s", folder)
    return removed
