"""`tabs rename`: give a child tab the title of the work it holds now.

    tabs rename <child id> <title>
                                the title the list shows for a child this tab opened. Only the parent can change it.

`tabs.py` reads the command word and hands the rest here with its way of calling the backend. The door is
`POST /sessions/{parent}/children/{child}/title` (`backend/routes/child_sessions.py`), which checks whose child it is;
the tab that asks is `PWA_SID`. A failure goes to stderr as `tabs: <reason>` and the command ends with 1.
"""
from __future__ import annotations

import os
import sys
import urllib.parse
from collections.abc import Callable

USAGE = "tabs rename <child id> <title>"


def run(argv: list[str], call: Callable[..., tuple[int, object]]) -> int:
    """Run `tabs rename` with `argv` (= the words after `rename`)."""
    if len(argv) != 2 or not argv[1].strip():
        print(f"usage: {USAGE}", file=sys.stderr)
        return 2
    parent = os.environ.get("PWA_SID")
    if not parent:
        print("tabs: rename works only inside a tab of the client (PWA_SID is not set)", file=sys.stderr)
        return 1
    child, title = argv
    status, body = call(f"/sessions/{urllib.parse.quote(parent)}/children/{urllib.parse.quote(child)}/title",
                        {"title": title.strip()})
    if status != 200 or not isinstance(body, dict):
        detail = body.get("detail") if isinstance(body, dict) else None
        code = detail.get("code") if isinstance(detail, dict) else None
        message = detail.get("message") if isinstance(detail, dict) else detail
        print(f"tabs: {child} was not renamed [{code or status}]: {message}", file=sys.stderr)
        return 1
    print(f"renamed: {child}  {body.get('title')}")
    return 0
