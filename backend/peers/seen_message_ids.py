"""The ids of the messages this machine took, so that a message sent twice is delivered once.

A message carries an id (`message_id`). The machine that receives it writes the id as `in_flight` before it starts
delivering, and as `done` once the message was typed into the tab (or kept for it); when delivering fails, the id is
forgotten again so that a later send can deliver it. An id that is `done` is answered as a duplicate without typing
anything; one that is `in_flight` is refused (409), since the first delivery has not finished. An id is remembered for
`RETENTION_SEC`, longer than a kept message is kept (`outbox_judgement.EXPIRY_SEC`). `in_flight` ids are dropped when
the backend starts (`forget_in_flight`): the delivery they stand for died with the process.

Used by `routes/agent_messages.py` (the `message_id` of `POST /agent-messages` and of a message handed over from
another machine) and by the backend's startup.
"""
from __future__ import annotations

import contextlib
import json
import logging
import threading
import time
from collections.abc import Iterator

from backend._common.errors import raise_error
from backend._common.paths import SEEN_MESSAGE_IDS_PATH
from backend._common.state import atomic_write_text

logger = logging.getLogger(__name__)

# 72 hours a message is kept for another machine, plus a day.
RETENTION_SEC = 96 * 3600
# What `claim` answers.
CLAIMED = "claimed"
ALREADY_DONE = "already_done"
STILL_IN_FLIGHT = "still_in_flight"
_IN_FLIGHT = "in_flight"
_DONE = "done"

# One lock for the whole file (a change reads it first).
_lock = threading.Lock()


def _load() -> dict:
    try:
        seen = json.loads(SEEN_MESSAGE_IDS_PATH.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    except (OSError, ValueError):
        logger.warning("seen message ids could not be read, starting them again: %s", SEEN_MESSAGE_IDS_PATH)
        return {}
    return seen if isinstance(seen, dict) else {}


def _save(seen: dict, now: float) -> None:
    kept = {key: row for key, row in seen.items() if isinstance(row, dict) and now - row.get("at", 0) <= RETENTION_SEC}
    atomic_write_text(SEEN_MESSAGE_IDS_PATH, json.dumps(kept, indent=2))


def claim(message_id: str, now: float | None = None) -> str:
    """Take `message_id` for delivery. → `CLAIMED` (it is written as in flight: the caller delivers), `ALREADY_DONE` or
    `STILL_IN_FLIGHT`."""
    now = time.time() if now is None else now
    with _lock:
        seen = _load()
        row = seen.get(message_id)
        if isinstance(row, dict) and now - row.get("at", 0) <= RETENTION_SEC:
            return ALREADY_DONE if row.get("state") == _DONE else STILL_IN_FLIGHT
        seen[message_id] = {"state": _IN_FLIGHT, "at": now}
        _save(seen, now)
        return CLAIMED


def complete(message_id: str, now: float | None = None) -> None:
    """The message was delivered: remember it for `RETENTION_SEC`."""
    now = time.time() if now is None else now
    with _lock:
        seen = _load()
        seen[message_id] = {"state": _DONE, "at": now}
        _save(seen, now)


def release(message_id: str) -> None:
    """Delivering failed: forget the id, so that a later send delivers the message."""
    with _lock:
        seen = _load()
        if seen.pop(message_id, None) is not None:
            _save(seen, time.time())


def forget_in_flight() -> None:
    """Drop every id that was in flight (= called when the backend starts)."""
    with _lock:
        seen = _load()
        left = {key: row for key, row in seen.items() if not (isinstance(row, dict) and row.get("state") == _IN_FLIGHT)}
        if left != seen:
            _save(left, time.time())


@contextlib.contextmanager
def delivering(message_id: str | None) -> Iterator[bool]:
    """Around the delivery of a message that may carry an id. Yields True when the caller is to deliver it, False when
    the id was delivered already (= answer it as a duplicate and type nothing). The id is remembered as delivered when
    the block ends, and forgotten when it raises. A message with no id (`None`) is always delivered. 409
    `agent_message_in_flight` when the same id is being delivered now."""
    if message_id is None:
        yield True
        return
    outcome = claim(message_id)
    if outcome == ALREADY_DONE:
        yield False
        return
    if outcome == STILL_IN_FLIGHT:
        raise_error(409, "agent_message_in_flight", "同じ連絡をまだ届けている途中です。 少し待って送り直してください")
    try:
        yield True
    except BaseException:
        release(message_id)
        raise
    complete(message_id)
