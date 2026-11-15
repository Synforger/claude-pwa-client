"""The record of whether each other machine answers: one JSON file, read and written under one lock.

Used by `peer_health.py` (writes) and `peer_send.py` (reads).
"""
from __future__ import annotations

import json
import logging
import threading
from collections.abc import Callable

from backend._common.paths import PEER_HEALTH_PATH
from backend._common.state import atomic_write_text

logger = logging.getLogger(__name__)

# One lock for the whole file: a record is changed by reading it, so two changes at once must not both read the old one.
_lock = threading.Lock()


def _load() -> dict:
    try:
        records = json.loads(PEER_HEALTH_PATH.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    except (OSError, ValueError):
        logger.warning("peer health record could not be read, starting it again: %s", PEER_HEALTH_PATH)
        return {}
    return records if isinstance(records, dict) else {}


def get(name: str) -> dict | None:
    """The record of the machine `name`, or None before it was first looked at."""
    with _lock:
        record = _load().get(name)
    return record if isinstance(record, dict) else None


def update(name: str, change: Callable[[dict | None], dict]) -> dict:
    """Replace the record of `name` with `change(its record now)` (= None when it has none), and return the new one."""
    with _lock:
        records = _load()
        previous = records.get(name)
        records[name] = change(previous if isinstance(previous, dict) else None)
        atomic_write_text(PEER_HEALTH_PATH, json.dumps(records, ensure_ascii=False, indent=2))
        return records[name]
