"""Moves a tab to another account in place: the same tab, with the same name, continues its conversation under the
other account. The conversation up to its latest clean point is written into that account's projects folder, the
tab's claude is stopped, and the tab starts again resuming it there.

Used by `routes/sessions.py` (= the operator moving a tab by hand) and by the account fallback
(`account_fallback/fallback_patrol.py`), which also records where the tab belongs and removes the record the client
wrote into the account the tab leaves.
"""
from __future__ import annotations

import asyncio
import logging
from pathlib import Path

import backend._common.config as config
from backend._common.config import default_account_id
from backend._common.errors import raise_error
from backend._common.state import SessionDef, save_sessions_meta, sessions_meta, sessions_overview
from backend.accounts.tab_restart import reset_tab_status, stop_tab_claude
from backend.fork.lineage import LineageCut, write_lineage
from backend.jsonl import resolver as jsonl_resolver

logger = logging.getLogger(__name__)


async def move_tab_account(session_id: str, account_id: str, *, cut: LineageCut = LineageCut.CLEAN_TURN,
                           fallback_from: str | None = None) -> SessionDef:
    """Move the tab to `account_id` (= an account of the configuration) and return its definition. A tab already on
    that account is left alone. A tab with no conversation yet (= a tier tab before its first message) only changes
    its account. `cut` says where the conversation is carried to. `fallback_from` is the account the tab belongs to
    when this move is the account fallback's (= it then runs elsewhere on purpose); any other move leaves the tab
    belonging to the account it moves to. Raises the HTTP error of `write_lineage` when there is no point to carry
    the conversation from, and `spawn_failed` when the tab cannot be opened under the new account."""
    meta = sessions_meta[session_id]
    if account_id == (meta.account_id or default_account_id()):
        return meta
    if (jsonl_resolver.resolve_jsonl(session_id, prefer="live") is None and not meta.resume_session_id
            and meta.sleeping_claude_sid() is None):
        # A tab with no conversation yet (= a tier tab before its first message) only changes its account: there is
        # nothing to carry over, and its first message starts it under the new account.
        meta.account_id = account_id
        meta.fallback_from = fallback_from
        save_sessions_meta()
        sessions_overview.notify()
        return meta
    written = await asyncio.to_thread(write_lineage, session_id, None, account_id, cut=cut)
    await stop_tab_claude(session_id)
    previous_copy = meta.fallback_copy
    meta.account_id = account_id
    meta.resume_session_id = written.claude_id
    meta.fallback_from = fallback_from
    meta.fallback_copy = str(written.path) if fallback_from is not None and written.moved else None
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
    if previous_copy is not None:
        remove_written_copy(previous_copy)
    return meta


def remove_written_copy(path: str) -> bool:
    """Delete a record the client wrote into an account's projects folder for a fallback move, once the tab has left
    that account. Only a `.jsonl` file directly inside a project folder of a configured account is deleted: what
    the tab's data holds is never trusted to name any other file. True when a file was deleted."""
    target = Path(path)
    if target.suffix != ".jsonl" or target.parent.parent not in config.CLAUDE_PROJECTS_DIRS:
        logger.warning("account move: not deleting %s, it is not a record in an account's projects folder", path)
        return False
    try:
        target.unlink()
    except FileNotFoundError:
        return False
    except OSError:
        logger.warning("account move: could not delete the record the client wrote: %s", path, exc_info=True)
        return False
    logger.info("account move: deleted the record the client wrote path=%s", path)
    return True
