"""Moves a tab to another account in place: the same tab, with the same name, continues its conversation under the
other account. The conversation up to its latest clean point is written into that account's projects folder, the
tab's claude is stopped, and the tab starts again resuming it there. When the two accounts keep their records in one
folder, the tab reopens the same conversation (same id) whenever the record can be opened as it is
(`shared_reopen.py`), and otherwise the conversation is written as a new session next to its source.

Used by `routes/sessions.py` (= the operator moving a tab by hand, which pins the tab to the account it chose) and by
the account fallback (`account_fallback/fallback_patrol.py`), which also records where the tab belongs and removes the
record the client wrote into the account the tab leaves (never one of a folder the accounts share: it is the tab's
conversation).
"""
from __future__ import annotations

import asyncio
import logging
from pathlib import Path

import backend._common.config as config
from backend._common.config import default_account_id
from backend._common.errors import raise_error
from backend._common.state import SessionDef, save_sessions_meta, sessions_meta, sessions_overview
from backend.accounts.shared_reopen import record_to_reopen
from backend.accounts.tab_restart import reset_tab_status, stop_tab_claude
from backend.fork.lineage import LineageCut, WrittenLineage, write_lineage
from backend.jsonl import resolver as jsonl_resolver
from backend.sleep.sleep_sensors import note_woken

logger = logging.getLogger(__name__)


async def move_tab_account(session_id: str, account_id: str, *, cut: LineageCut = LineageCut.CLEAN_TURN,
                           fallback_from: str | None = None, pin: bool = False, at_break: bool = False) -> SessionDef:
    """Move the tab to `account_id` (= an account of the configuration) and return its definition. A tab already on
    that account is left alone. A tab with no conversation yet (= a tier tab before its first message) only changes
    its account. `cut` says where the conversation is carried to. `fallback_from` is the account the tab belongs to
    when this move is the account fallback's (= it then runs elsewhere on purpose); any other move leaves the tab
    belonging to the account it moves to. `pin` is the operator's own move: the tab is pinned to the account it was moved
    to, in the same step that writes the account, and a tab that is on that account already belongs to it from now on
    (`fallback_from` is cleared) and is pinned too: the pin brings a pinned tab back to the account it belongs to, so
    a stale `fallback_from` would send it back off the account that was chosen. Raises the HTTP error of
    `write_lineage` when there is no point to carry the conversation from (then the tab is not pinned), and
    `tab_not_stopped` when its claude could not be stopped (nothing of the tab is then changed), and
    `spawn_failed` when the tab cannot be opened under the new account (it is pinned: it runs there). `at_break` says
    the caller has found the tab at a break (a running tab is then reopened as it is when the accounts share their
    records; the operator's own move leaves it false, and writes the conversation out)."""
    meta = sessions_meta[session_id]
    if account_id == (meta.account_id or default_account_id()):
        if pin:
            meta.fallback_from = None
            meta.account_pinned = True
            save_sessions_meta()
            sessions_overview.notify()
        return meta
    if (jsonl_resolver.resolve_jsonl(session_id, prefer="live") is None and not meta.resume_session_id
            and meta.sleeping_claude_sid() is None):
        # A tab with no conversation yet (= a tier tab before its first message) only changes its account: there is
        # nothing to carry over, and its first message starts it under the new account.
        meta.account_id = account_id
        meta.fallback_from = fallback_from
        meta.account_pinned = meta.account_pinned or pin
        save_sessions_meta()
        sessions_overview.notify()
        return meta
    reopened = await asyncio.to_thread(record_to_reopen, session_id, account_id, cut, at_break=at_break)
    written: WrittenLineage | None = None
    if reopened is None:
        written = await asyncio.to_thread(write_lineage, session_id, None, account_id, cut=cut)
    claude_id = reopened.claude_id if reopened is not None else written.claude_id
    if not await stop_tab_claude(session_id):
        if written is not None:
            # the new record is the client's own and no claude opened it: it goes by its own path, whichever folder it is in
            written.path.unlink(missing_ok=True)
        raise_error(409, "tab_not_stopped", "このタブの Claude を止められなかったので、 口座は移していません")
    previous_copy = meta.fallback_copy
    meta.account_id = account_id
    meta.resume_session_id = claude_id
    meta.fallback_from = fallback_from
    meta.fallback_copy = str(written.path) if fallback_from is not None and written is not None and written.moved else None
    meta.account_pinned = meta.account_pinned or pin
    if meta.sleeping_claude_sid() is not None:
        # a sleep mark that still names a conversation the tab can reopen (= the accounts share their records) is
        # read before `resume_session_id`, and would open the old conversation instead of the one chosen here
        meta.sleep = None
        note_woken(session_id)
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


def _is_projects_folder(folder: Path) -> bool:
    """Whether `folder` is the projects folder of a configured account (the same folder, however it is spelled)."""
    key = config.entity_key(folder)
    return key is not None and any(config.entity_key(known) == key for known in config.CLAUDE_PROJECTS_DIRS)


def remove_written_copy(path: str) -> bool:
    """Delete a record the client wrote into an account's projects folder for a fallback move, once the tab has left
    that account. Only a `.jsonl` file directly inside a project folder of a configured account is deleted: what
    the tab's data holds is never trusted to name any other file. A folder that two accounts share holds the tab's
    own conversation, so nothing in it is deleted. True when a file was deleted."""
    target = Path(path)
    folder = target.parent.parent
    if target.suffix != ".jsonl" or not _is_projects_folder(folder):
        logger.warning("account move: not deleting %s, it is not a record in an account's projects folder", path)
        return False
    if len(config.accounts_sharing(folder)) > 1:
        logger.info("account move: not deleting %s, the accounts share this folder", path)
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
