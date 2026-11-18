"""The file of one ticket, `<place>/<id>.jsonl`: lines that are only ever added. The backend is its one writer, and a lock
per ticket keeps two lines added at once from mixing. Called by `ticket_service.py`.
"""
from __future__ import annotations

import threading
from pathlib import Path

from backend.tickets import ticket_entry

_locks: dict[str, threading.Lock] = {}
_locks_guard = threading.Lock()


def lock_for(ticket_id: str) -> threading.Lock:
    """The lock of one ticket, to hold while its file and its row of the index change together."""
    with _locks_guard:
        return _locks.setdefault(ticket_id, threading.Lock())


def path_of(folder: Path, ticket_id: str) -> Path:
    return folder / f"{ticket_id}.jsonl"


def create(folder: Path, ticket_id: str, entries: list[dict]) -> bool:
    """Write the first lines of a new ticket. → False when a file of that id is there already (= nothing is written)."""
    folder.mkdir(parents=True, exist_ok=True)
    try:
        with path_of(folder, ticket_id).open("x", encoding="utf-8") as file:
            file.write("".join(ticket_entry.to_line(entry) for entry in entries))
    except FileExistsError:
        return False
    return True


def append(folder: Path, ticket_id: str, entry: dict) -> None:
    """Add one line. The caller holds `lock_for(ticket_id)` when the row of the index changes with it."""
    with path_of(folder, ticket_id).open("a", encoding="utf-8") as file:
        file.write(ticket_entry.to_line(entry))


def read(folder: Path, ticket_id: str) -> list[dict]:
    """All the lines of the ticket by time. Empty when the file is not there."""
    try:
        return ticket_entry.parse_lines(path_of(folder, ticket_id).read_text(encoding="utf-8"))
    except OSError:
        return []
