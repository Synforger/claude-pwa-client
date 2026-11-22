"""Finds the record a tab's conversation can be reopened from under another account, as it is, when the two accounts
keep their conversation records in one folder (`_common.config.projects_shared`). Reads the record; whether it may be
reopened as it is, is `reopen_judgement.py`.

Used by `account_move.py`, which then opens the same conversation under the other account instead of writing it out
as a new session.
"""
from __future__ import annotations

from pathlib import Path
from typing import NamedTuple

import backend.jsonl.jsonl_watcher as jsonl_watcher
from backend._common import config as _config
from backend._common.state import sessions_meta
from backend.accounts.reopen_judgement import reopens_as_is
from backend.fork.lineage import LineageCut


class ReopenRecord(NamedTuple):
    """The conversation a move reopens as it is: its claude session id and the record's path."""
    claude_id: str
    path: Path


def record_to_reopen(session_id: str, target_account_id: str, cut: LineageCut, *, at_break: bool) -> ReopenRecord | None:
    """The record `session_id`'s conversation is reopened from under `target_account_id`, None when the move has to
    write the conversation out instead: the accounts do not share their records, the tab's record is not found where the
    other account opens it, or it cannot be reopened as it is (`reopens_as_is`).

    A running claude is read only when the caller has found the tab at a break (`at_break`: the account fallback has
    read it; the operator's own move has not, and a turn may be going on). A sleeping tab is at a break by itself: its
    conversation is the one its sleep mark names, whichever account the mark was made under. Blocks on reading the
    record; call it off the event loop."""
    meta = sessions_meta[session_id]
    sleeping = meta.sleep
    if sleeping is not None:
        claude_id, path, source_account = sleeping.claude_sid, Path(sleeping.record), sleeping.account_id
    elif at_break:
        live = jsonl_watcher.get_jsonl_for(session_id)
        if live is None:
            return None
        claude_id, path, source_account = live.stem, live, meta.account_id
    else:
        return None
    if not _config.projects_shared(source_account, target_account_id):
        return None
    cwd = (_config.AGENTS.get(meta.agent_id) or {}).get("cwd")
    if not cwd or not path.is_file():
        return None
    # the record must be the file the other account's claude finds for this working folder
    opened_from = _config.cwd_to_project_dir(cwd, account_id=target_account_id) / f"{claude_id}.jsonl"
    key = _config.entity_key(path)
    if key is None or key != _config.entity_key(opened_from):
        return None
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return None
    return ReopenRecord(claude_id, path) if reopens_as_is(text, cut) else None
