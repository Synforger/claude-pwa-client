"""The template a tab's top page is made from, as pure functions: where the agent keeps it and how a tab's
title, tier and place are filled in.

The template is `pages/_template-tab/index.html` in the agent's folder (= one per agent, not per tier). It has
three fill-in marks, `{{title}}`, `{{tier}}` and `{{pages_root}}` (= the way from the page's folder up to the
agent's own `pages` folder, which holds the parts every page shares and is a different number of folders away in
each tier); every other character is kept. It also holds the fingerprint of a
filled page, which ignores the lines a tool adds to every page of a tier (= a script load). Called by `tab_page`
(to record the fingerprint of the page it made) and `child_folder` (to tell an untouched page).
"""

from __future__ import annotations

import hashlib
import html
import os
import re
from pathlib import Path

from backend.terminal.tab_memo import PAGE_NAME, PAGES_FOLDER

TEMPLATE_FOLDER = "_template-tab"

_MARK = re.compile(r"\{\{(title|tier|pages_root)\}\}")

#: A line that only loads a script (= `<script src="…" defer></script>`): a tool adds such a line to every page
SCRIPT_LINE = re.compile(r'\s*<script\s+src="[^"]*"(\s+[a-z-]+(="[^"]*")?)*\s*>\s*</script>\s*', re.IGNORECASE)


def template_file(agent_folder: Path) -> Path:
    """The top page template of the agent whose folder is `agent_folder`."""
    return agent_folder / PAGES_FOLDER / TEMPLATE_FOLDER / PAGE_NAME


def pages_root_from(agent_folder: Path, page_folder: Path) -> str:
    """The relative path from `page_folder` (= the folder a top page is written in) to the agent's `pages` folder,
    with `/` and no trailing one: `..` for a tab of the agent's own folder, `../../../../pages` for a tab of
    `projects/<name>`. Only the paths are compared; nothing is read from the disk."""
    return Path(os.path.relpath(agent_folder / PAGES_FOLDER, page_folder)).as_posix()


def fill_template(template: str, *, title: str, tier: str, pages_root: str) -> str:
    """`template` with `{{title}}`, `{{tier}}` and `{{pages_root}}` replaced by the tab's title, its tier and the
    way up to the agent's `pages` folder (`pages_root_from`), escaped for HTML. The marks are replaced in one pass,
    so a title that contains a mark is not filled in a second time."""
    values = {"title": html.escape(title), "tier": html.escape(tier), "pages_root": html.escape(pages_root)}
    return _MARK.sub(lambda mark: values[mark.group(1)], template)


def without_script_lines(text: str) -> str:
    """`text` without the lines that only load a script (= what is left to compare with a filled template)."""
    return "\n".join(line for line in text.splitlines() if not SCRIPT_LINE.fullmatch(line))


def page_fingerprint(text: str) -> str:
    """The sha256 (hex) of a top page without its script-load lines. Two pages with the same fingerprint differ
    at most by such lines."""
    return hashlib.sha256(without_script_lines(text).encode("utf-8")).hexdigest()
