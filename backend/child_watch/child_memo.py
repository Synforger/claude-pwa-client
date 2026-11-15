"""The state line of a child tab's memo (`- 状態: 作業中`): `tabs report` rewrites it, the backend sets it back to
working when the parent hands the child more work, and `tabs children`, the startup check and the child watch read it. Standard library only, because the `tabs` command imports it without the
backend's dependencies.

Used by `backend/cli/tabs.py`, `watch_sensors.py` and `child_work.py`.
"""
from __future__ import annotations

import os
import re
from pathlib import Path

#: The state line of a memo: the whole line, and the state after the label as group 1.
STATE_LINE = re.compile(r"^- 状態: (.*)$", re.M)
#: The state of a child that has not reported (the memo is written with it when the child is opened).
WORKING = "作業中"
#: The states `tabs report done` and `tabs report stuck` write.
DONE = "完了"
STUCK = "詰まり"
#: What `memo_state` answers for a memo that is missing, unreadable or without the line.
UNKNOWN = "?"
#: How many times `save_memo_state` reads the memo again when the file changed under it, before it gives up.
SAVE_ATTEMPTS = 5


def memo_state(path: Path | None) -> str:
    """The state the memo at `path` names; `UNKNOWN` when there is no memo or it has no state line."""
    try:
        found = STATE_LINE.search(path.read_text(encoding="utf-8")) if path is not None else None
    except (OSError, UnicodeDecodeError):
        found = None
    return found.group(1).strip() if found else UNKNOWN


def with_state(text: str, state: str) -> str:
    """`text` (a memo) with its state line saying `state`; a memo without the line gets one at the top."""
    line = f"- 状態: {state}"
    if STATE_LINE.search(text):
        return STATE_LINE.sub(line, text, count=1)
    return f"{line}\n\n{text}"


def _read_memo_bytes(path: Path) -> bytes:
    return path.read_bytes()


def save_memo_state(path: Path, state: str) -> None:
    """Write `state` into the state line of the memo at `path`, and change nothing else in it.

    The memo is also written by its tab's agent and by the screen, so the file is read again just before it is
    replaced: when it changed since the first read, the new text is taken and the line set again (up to
    `SAVE_ATTEMPTS` times, then `OSError`). The text is replaced through a file of its own, so no reader sees half of
    it. A memo that already says `state` is not written at all."""
    target = Path(os.path.realpath(path))
    for _ in range(SAVE_ATTEMPTS):
        seen = _read_memo_bytes(target)
        written = with_state(seen.decode("utf-8"), state).encode("utf-8")
        if _read_memo_bytes(target) != seen:
            continue
        if written != seen:
            staged = target.with_name(target.name + ".tmp")
            staged.write_bytes(written)
            os.replace(staged, target)
        return
    raise OSError(f"the memo kept changing while its state was written: {path}")
