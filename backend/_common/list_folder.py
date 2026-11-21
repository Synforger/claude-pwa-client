"""The folder of the conversation list a tab goes in (`<agent id>/<folder>/...`), as an agent's setting or a tab's own.

Read by the agents view (`routes/accounts.py`), the stored tab definition (`_common/state.py`) and the doors that set a
tab's folder (`routes/sessions.py`). The screen places tabs by the same shape
(`frontend/src/features/session-drawer/folderTree.js`).
"""
from __future__ import annotations


def parse_list_folder(value: object) -> str | None:
    """The folder with each name trimmed. → None when it is not text, names no folder below the agent, or has an empty
    name."""
    if not isinstance(value, str):
        return None
    names = [name.strip() for name in value.split("/")]
    if len(names) < 2 or not all(names):
        return None
    return "/".join(names)
