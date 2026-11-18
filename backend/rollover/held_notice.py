"""Tells a conversation once why it is not asked to close: it is past its working line (`context`) while its tools
run commands in the background, which the end of the conversation would stop (`held_envelope.py`).

The notice is typed only into a running claude, the way the ask to close is (`pty_send`), and only when typing it
changes nothing else: not into a conversation that ends in a usage-limit stop or still owes the continuation of one
(a typed prompt counts as the operator's and would settle it), and not while the account hold or the account fallback
has asked the tab to stop or to carry on. Such a tab is looked at again on the next look.

One notice per conversation (= its record). What was told is kept in memory and, for a record not seen yet (after a
restart of the backend), read from the record itself. A notice typed counts as told even when it did not reach the
record, so it is never typed on every look.

Used by `rollover.py`.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path

from backend._common.state import sessions_meta
from backend.jsonl.jsonl_predicates import CLIENT_NOTICE_OPENING, unwrap_pasted
from backend.rollover.held_envelope import TAG, held_envelope
from backend.rollover.tool_shells import ToolShell
from backend.routes.agent_messages import entered_text
from backend.terminal.pty_discover import claude_in_pane
from backend.terminal.routes import pty_send

logger = logging.getLogger(__name__)

LIMIT = "limit"
ACCOUNT = "account"
NO_CLAUDE = "no_claude"

_MARK = f"<{TAG} ".encode()

# Per record: whether the conversation was told (= read from the record the first time it is seen).
_told: dict[str, bool] = {}
# Per record: the reason the last notice was put off (= the log says so when it changes).
_deferred: dict[str, str] = {}


def told_in(record: Path) -> bool:
    """Whether the record holds a notice the client typed (= typed, or queued while the conversation worked). Blocking."""
    try:
        with record.open("rb") as fh:
            for raw in fh:
                if _MARK not in raw:
                    continue
                try:
                    row = json.loads(raw)
                except ValueError:
                    continue
                text = entered_text(row) if isinstance(row, dict) else None
                if text and unwrap_pasted(text).lstrip().startswith(CLIENT_NOTICE_OPENING):
                    return True
    except OSError:
        return False
    return False


def blocker(session_id: str, record: Path) -> str | None:
    """Why a notice may not be typed into the tab now (`LIMIT`, `ACCOUNT`), None when it may. Blocking."""
    # Imported here: the sleep package reads the rollover watch, which imports this module.
    from backend.sleep.sleep_sensors import record_facts_of  # noqa: PLC0415
    meta = sessions_meta.get(session_id)
    if meta is not None and (meta.pause_asked_at or meta.hold_asked_at or meta.owes_carry_on):
        return ACCOUNT
    try:
        facts = record_facts_of(record)
    except OSError:
        return LIMIT
    if facts.limit_stop is not None or facts.continuation_owed is not None:
        return LIMIT
    return None


def was_told(key: str, record: Path) -> bool:
    """Whether the conversation of `record` was told already. Blocking on the first look at a record."""
    if key not in _told:
        _told[key] = told_in(record)
    return _told[key]


def _log_deferred(session_id: str, key: str, reason: str) -> None:
    if _deferred.get(key) == reason:
        return
    _deferred[key] = reason
    logger.info("rollover: notice deferred session=%s reason=%s", session_id, reason)


async def tell(session_id: str, key: str, reason: str, context_pct: int | None, line_pct: float | None,
               shells: list[ToolShell], why_not: str | None) -> None:
    """Type the notice into the tab, unless `why_not` (from `blocker`) or a claude that is gone puts it off."""
    if why_not is None and not claude_in_pane(session_id):
        why_not = NO_CLAUDE
    if why_not is not None:
        _log_deferred(session_id, key, why_not)
        return
    _told[key] = True
    _deferred.pop(key, None)
    result = await pty_send(session_id, {"text": held_envelope(reason, context_pct, line_pct, shells), "enter": True},
                            None)
    logger.info("rollover: told held session=%s context_pct=%s background=%s ok=%s", session_id, context_pct,
                ",".join(str(shell.pid) for shell in shells), result.get("ok"))


def forget(records: set[str]) -> None:
    """Drop what is kept for records that are gone."""
    for table in (_told, _deferred):
        for key in [k for k in table if k not in records]:
            del table[key]
