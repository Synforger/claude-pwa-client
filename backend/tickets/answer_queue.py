"""`answer-queue.json`, the answers the operator gave that have not reached the tab that holds the ticket. One entry is the
key `(ticket id, asked_at)` and nothing else: the words are read from the ticket's own file (the `answered` line) when the
answer is delivered, so the queue holds no text. The same key is never added twice. Called by `ticket_answer.py`,
`answer_delivery.py` and `ticket_pass.py`.
"""
from __future__ import annotations

import json
import os
import threading
from pathlib import Path
from typing import NamedTuple

from backend._common import paths

QUEUE_NAME = "answer-queue.json"
_lock = threading.RLock()


class AnswerKey(NamedTuple):
    """The answer to one `asked` line of one ticket (= `asked_at` is that line's `at`)."""

    ticket: str
    asked_at: str


def _queue_path() -> Path:
    return paths.TICKETS_DIR / QUEUE_NAME


def _is_key(item: object) -> bool:
    return isinstance(item, dict) and isinstance(item.get("ticket"), str) and isinstance(item.get("asked_at"), str)


def keys() -> list[AnswerKey]:
    """The answers waiting, oldest first. Empty when there is no queue file or it cannot be read."""
    try:
        raw = json.loads(_queue_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    if not isinstance(raw, list):
        return []
    return list(dict.fromkeys(AnswerKey(item["ticket"], item["asked_at"]) for item in raw if _is_key(item)))


def contains(key: AnswerKey) -> bool:
    return key in keys()


def pending_for(ticket: str) -> bool:
    """Whether an answer to this ticket waits to reach its holder."""
    return any(key.ticket == ticket for key in keys())


def add(key: AnswerKey) -> bool:
    """Put the answer in the queue. → False when the same key is there already (= nothing changes)."""
    with _lock:
        current = keys()
        if key in current:
            return False
        _write([*current, key])
        return True


def remove(key: AnswerKey) -> None:
    """Take the answer out of the queue (= it was delivered, or there is nothing left to deliver it to)."""
    with _lock:
        current = keys()
        if key in current:
            _write([other for other in current if other != key])


def _write(entries: list[AnswerKey]) -> None:
    """Write the queue whole, through a file of its own and a rename, so that a reader never sees half of it."""
    path = _queue_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    scratch = path.with_name(f"{QUEUE_NAME}.{os.getpid()}.tmp")
    scratch.write_text(json.dumps([{"ticket": key.ticket, "asked_at": key.asked_at} for key in entries],
                                  ensure_ascii=False, indent=1), encoding="utf-8")
    os.replace(scratch, path)
