"""The messages kept for a machine that did not answer: one file each, `<id>.json` in the outbox folder.

An entry is `{id, peer, to, from_session, from_title, text, kept_at, tries}` (`to` is the tab on that machine, `kept_at`
is epoch seconds). One file per message means a keep, a delete and a count of tries never rewrite another message.

Used by `peer_send.py` (keeps) and `outbox_flush.py` (lists, counts tries, deletes).
"""
from __future__ import annotations

import json
import logging

from backend._common.paths import PEER_OUTBOX_DIR
from backend._common.state import atomic_write_text

logger = logging.getLogger(__name__)


def _write(entry: dict) -> None:
    PEER_OUTBOX_DIR.mkdir(parents=True, exist_ok=True)
    atomic_write_text(PEER_OUTBOX_DIR / f"{entry['id']}.json", json.dumps(entry, ensure_ascii=False, indent=2))


def keep(entry: dict) -> None:
    """Keep `entry` (a new message). Raises OSError when it cannot be written."""
    _write(entry)


def pending(peer: str | None = None) -> list[dict]:
    """The kept messages, oldest first: those for the machine `peer`, or for every machine when it is None. A file that
    cannot be read is left alone and logged."""
    entries = []
    for path in sorted(PEER_OUTBOX_DIR.glob("*.json")) if PEER_OUTBOX_DIR.is_dir() else ():
        try:
            entry = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            logger.warning("kept message could not be read: %s", path)
            continue
        if isinstance(entry, dict) and isinstance(entry.get("id"), str) and (peer is None or entry.get("peer") == peer):
            entries.append(entry)
    return sorted(entries, key=lambda entry: (entry.get("kept_at", 0), entry["id"]))


def count_try(entry: dict) -> dict:
    """Write one more try into `entry` and return it. A message that was deleted meanwhile is not written again."""
    counted = {**entry, "tries": entry.get("tries", 0) + 1}
    if (PEER_OUTBOX_DIR / f"{entry['id']}.json").exists():
        _write(counted)
    return counted


def remove(entry_id: str) -> None:
    """Delete a kept message (= it arrived, was refused for good, or ran out of time)."""
    (PEER_OUTBOX_DIR / f"{entry_id}.json").unlink(missing_ok=True)
