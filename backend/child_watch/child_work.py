"""The memo of a child tab as the backend keeps it: where it is, and setting it back to working when the parent hands
the child more work. A child that reported (`完了` / `詰まり`) and then takes the next piece of work from its parent
holds work again; with its memo left at the report, `tabs children`, the child watch and `tabs close` would take it
for a child with nothing to do. Blocking (files).

Used by `watch_sensors.py` and `backend/routes/agent_messages.py` (= a message the parent delivered to its child).
"""
from __future__ import annotations

import logging
from pathlib import Path

from backend._common.state import SessionDef, sessions_meta
from backend.child_watch.child_memo import WORKING, memo_state, save_memo_state
from backend.terminal.tab_memo import memo_file, tier_folder

logger = logging.getLogger(__name__)


def memo_of(meta: SessionDef) -> Path | None:
    """The child's memo: in the tier folder of the child, or of its parent (`tabs new` writes it in the parent's)."""
    for tab_id in (meta.id, meta.parent_id):
        if tab_id in sessions_meta:
            path = memo_file(tier_folder(tab_id), meta.id)
            if path.is_file():
                return path
    return None


def hand_work(sender_id: str, receiver_id: str) -> bool:
    """Note that `sender_id` delivered a message to `receiver_id`: when the receiver is a child of the sender whose
    memo names a report, the memo says working again. True when the memo was changed."""
    meta = sessions_meta.get(receiver_id)
    if meta is None or not meta.child or meta.parent_id != sender_id:
        return False
    path = memo_of(meta)
    if path is None:
        return False
    before = memo_state(path)
    if before == WORKING:
        return False
    try:
        save_memo_state(path, WORKING)
    except (OSError, UnicodeDecodeError):
        logger.warning("child work: the memo of session=%s could not be set to working: %s", receiver_id, path)
        return False
    logger.info("child work: the parent handed session=%s more work; memo %s -> %s", receiver_id, before, WORKING)
    return True
