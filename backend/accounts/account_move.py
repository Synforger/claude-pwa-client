"""Moves a tab to another account in place: the same tab, with the same name, continues its conversation under the
other account. The conversation up to its latest clean point is written into that account's projects folder, the
tab's claude is stopped, and the tab starts again resuming it there.

Used by `routes/sessions.py` (= the operator moving a tab by hand).
"""
from __future__ import annotations

import logging

from fastapi import HTTPException

from backend._common.config import default_account_id
from backend._common.errors import raise_error
from backend._common.state import SessionDef, save_sessions_meta, sessions_meta, sessions_overview
from backend.accounts.tab_restart import reset_tab_status, stop_tab_claude
from backend.fork.lineage import write_lineage
from backend.jsonl import resolver as jsonl_resolver

logger = logging.getLogger(__name__)


async def move_tab_account(session_id: str, account_id: str) -> SessionDef:
    """Move the tab to `account_id` (= an account of the configuration) and return its definition. A tab already on
    that account is left alone. A tab with no conversation yet (= a tier tab before its first message) only changes
    its account. Raises the HTTP error of `write_lineage` when there is no point to carry the conversation from, and
    `spawn_failed` when the tab cannot be opened under the new account."""
    meta = sessions_meta[session_id]
    if account_id == (meta.account_id or default_account_id()):
        return meta
    if (jsonl_resolver.resolve_jsonl(session_id, prefer="live") is None and not meta.resume_session_id
            and meta.sleeping_claude_sid() is None):
        # A tab with no conversation yet (= a tier tab before its first message) only changes its account: there is
        # nothing to carry over, and its first message starts it under the new account.
        meta.account_id = account_id
        save_sessions_meta()
        sessions_overview.notify()
        return meta
    new_claude_id, _moved = write_lineage(session_id, None, account_id)
    await stop_tab_claude(session_id)
    meta.account_id = account_id
    meta.resume_session_id = new_claude_id
    save_sessions_meta()
    from backend.jsonl.routes import request_sid_tail_reset  # noqa: PLC0415
    request_sid_tail_reset(session_id)
    from backend.terminal.routes import ensure_pty_session_for  # noqa: PLC0415
    try:
        await ensure_pty_session_for(session_id)
    except Exception:
        logger.exception("account move spawn phase failed for %s", session_id)
        raise_error(500, "spawn_failed", "移した先で会話を開けませんでした")
    await reset_tab_status(session_id)
    sessions_overview.notify()
    return meta
