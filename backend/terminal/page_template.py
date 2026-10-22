"""The template a tab's top page is made from, as pure functions: where the agent keeps it and how a tab's
title and tier are filled in.

The template is `pages/_template-tab/index.html` in the agent's folder (= one per agent, not per tier). It has
two fill-in marks, `{{title}}` and `{{tier}}`; every other character is kept. Called by `tab_page`.
"""

from __future__ import annotations

import html
import re
from pathlib import Path

from backend.terminal.tab_memo import PAGE_NAME, PAGES_FOLDER

TEMPLATE_FOLDER = "_template-tab"

_MARK = re.compile(r"\{\{(title|tier)\}\}")


def template_file(agent_folder: Path) -> Path:
    """The top page template of the agent whose folder is `agent_folder`."""
    return agent_folder / PAGES_FOLDER / TEMPLATE_FOLDER / PAGE_NAME


def fill_template(template: str, *, title: str, tier: str) -> str:
    """`template` with `{{title}}` and `{{tier}}` replaced by the tab's title and tier, escaped for HTML. The
    marks are replaced in one pass, so a title that contains a mark is not filled in a second time."""
    values = {"title": html.escape(title), "tier": html.escape(tier)}
    return _MARK.sub(lambda mark: values[mark.group(1)], template)
