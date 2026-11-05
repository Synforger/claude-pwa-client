"""The state line of a child tab's memo (`- 状態: 作業中`): `tabs report` rewrites it, and `tabs children`, the startup
check and the child watch read it. Standard library only, because the `tabs` command imports it without the
backend's dependencies.

Used by `backend/cli/tabs.py` and `watch_sensors.py`.
"""
from __future__ import annotations

import re
from pathlib import Path

#: The state line of a memo: the whole line, and the state after the label as group 1.
STATE_LINE = re.compile(r"^- 状態: (.*)$", re.M)
#: The state of a child that has not reported (the memo is written with it when the child is opened).
WORKING = "作業中"
#: What `memo_state` answers for a memo that is missing, unreadable or without the line.
UNKNOWN = "?"


def memo_state(path: Path | None) -> str:
    """The state the memo at `path` names; `UNKNOWN` when there is no memo or it has no state line."""
    try:
        found = STATE_LINE.search(path.read_text(encoding="utf-8")) if path is not None else None
    except (OSError, UnicodeDecodeError):
        found = None
    return found.group(1).strip() if found else UNKNOWN
