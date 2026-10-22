"""Moves the memos an earlier version kept in one folder to where each tab's memo lives now.

Earlier versions kept every memo as `<legacy folder>/<tab id>.md`, often a symlink to a file in the folder of
the tier the tab works in. Now a memo is `<tier folder>/pages/<tab id>/memo.md` (see `tab_memo`). Called once
by the backend at startup; a second call finds nothing left to move.
"""

from __future__ import annotations

import logging
import os
import shutil
from pathlib import Path

from backend import state
from backend.terminal.tab_memo import memo_file, memo_path

logger = logging.getLogger(__name__)

#: The folder an earlier version kept a tier's memo in, next to `pages/`
EARLIER_FOLDER = "notes"


def destination(legacy: Path, session_id: str) -> Path:
    """Where the memo of `session_id`, currently at `legacy`, belongs now.

    A symlink into `<folder>/notes/<tab id>.md` was placed there for the tier whose folder it is, so the memo
    stays in that folder. Any other memo goes where the tab's memo is placed now."""
    if legacy.is_symlink():
        target = Path(os.path.realpath(legacy))
        if target.parent.name == EARLIER_FOLDER:
            return memo_file(target.parent.parent, session_id)
    return memo_path(session_id)


def migrate_memos(legacy_folder: Path) -> list[str]:
    """Move every memo in `legacy_folder` of an existing tab to its place, and return a line for each one
    moved or left (= left when its place already holds a memo)."""
    records: list[str] = []
    if not legacy_folder.is_dir():
        return records
    for legacy in sorted(legacy_folder.glob("*.md")):
        session_id = legacy.stem
        if session_id not in state.sessions_meta:
            continue
        source = Path(os.path.realpath(legacy))
        if not source.is_file():
            if legacy.is_symlink():
                legacy.unlink()
            continue
        target = destination(legacy, session_id)
        if target.exists() and target != source:
            records.append(f"memo left in place (= {target} already exists): {legacy}")
            continue
        if target != source:
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(source, target)
            records.append(f"memo moved: {legacy} -> {target}")
        if legacy.is_symlink():
            legacy.unlink()
    for record in records:
        logger.info(record)
    try:
        legacy_folder.rmdir()
    except OSError:
        # benign: the folder still holds memos left in place (or tabs' files), which is the point of leaving it
        pass
    return records
