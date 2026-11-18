"""`index.json`, the list of every ticket on this machine: where it is kept, who holds it and its state. It holds no title
and no text, and no path of a folder either (= a boundary's folder is named only by its key, `ticket_places.py`), so what
the guard keeps out of `state/` stays out. Called by `ticket_service.py`.
"""
from __future__ import annotations

import json
import os
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import NamedTuple

from backend._common import paths

INDEX_NAME = "index.json"
OPEN = "open"
WAITING_OPERATOR = "waiting-operator"
CLOSED = "closed"
_lock = threading.RLock()


class IndexRow(NamedTuple):
    """What the index knows of one ticket. `wants` is what the ticket asks of the operator (= `decide`, `mac`, `report`)
    or None."""

    place_key: str
    holder: str
    opener: str
    status: str
    wants: str | None

    def to_json(self) -> dict:
        return self._asdict()

    @staticmethod
    def from_json(raw: object) -> IndexRow | None:
        """None when `raw` is not a row (= a damaged entry is skipped, not read as a ticket)."""
        if not isinstance(raw, dict) or not all(isinstance(raw.get(name), str) for name in
                                                ("place_key", "holder", "opener", "status")):
            return None
        wants = raw.get("wants")
        return IndexRow(raw["place_key"], raw["holder"], raw["opener"], raw["status"],
                        wants if isinstance(wants, str) else None)


def index_path() -> Path:
    return paths.TICKETS_DIR / INDEX_NAME


@contextmanager
def locked() -> Iterator[None]:
    """Hold the index for a read and the change that follows it (= no other change lands in between)."""
    with _lock:
        yield


def rows() -> dict[str, IndexRow]:
    """Every ticket's row by id."""
    try:
        raw = json.loads(index_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    found = {ticket_id: IndexRow.from_json(row) for ticket_id, row in raw.items()} if isinstance(raw, dict) else {}
    return {ticket_id: row for ticket_id, row in found.items() if row is not None}


def get(ticket_id: str) -> IndexRow | None:
    return rows().get(ticket_id)


def put(ticket_id: str, row: IndexRow) -> None:
    """Set the row of one ticket and write the index whole (= through a file of its own and a rename, so a reader never
    sees half of it)."""
    with _lock:
        everything = {**rows(), ticket_id: row}
        path = index_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        scratch = path.with_name(f"{INDEX_NAME}.{os.getpid()}.tmp")
        scratch.write_text(json.dumps({key: value.to_json() for key, value in sorted(everything.items())},
                                      ensure_ascii=False, indent=1), encoding="utf-8")
        os.replace(scratch, path)
