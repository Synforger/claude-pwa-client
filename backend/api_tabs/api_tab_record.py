"""Reading an API tab's record file: the one segment the replay reads, the end of its complete rows, the context amount
of its last answer, and what was appended since a position.

A record only ever grows by whole rows (`docs/reference/api-tabs.md`): a last row without its newline is a write in
progress, so nothing here reads past the last newline. Blocking file reads: callers run them in a thread. Used by
`api_tab_stream.py` and by the replay and history doors (`record_segments`).
"""
from __future__ import annotations

import json
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path

from backend.api_tabs.api_tab_table import current_table
from backend.api_tabs.context_tokens import context_tokens_of_row
from backend.jsonl.chain import Segment
from backend.jsonl.jsonl_tail import read_complete_lines_with_pos

#: How much of the file one backward step reads (= the same step as `jsonl_tail.initial_offset`).
BACKWARD_STEP_BYTES = 64 * 1024


def record_segments(tab_id: str) -> list[Segment] | None:
    """The segments the replay and the history read for `tab_id`: the one record file, from position 0 (an API tab has
    no earlier conversations to chain), or none while the file is not there yet. None when `tab_id` is not an API tab,
    so the caller reads a Claude tab's chain instead."""
    tab = current_table().tab(tab_id)
    if tab is None:
        return None
    return [Segment(tab.record, 0)] if tab.record.is_file() else []


def end_of_complete_lines(path: Path) -> int:
    """The position just after the last newline of `path` (0 when it has none): where the rows that are whole end."""
    pos = path.stat().st_size
    with path.open("rb") as handle:
        while pos > 0:
            step = min(BACKWARD_STEP_BYTES, pos)
            pos -= step
            handle.seek(pos)
            found = handle.read(step).rfind(b"\n")
            if found != -1:
                return pos + found + 1
    return 0


def _rows_from_the_end(path: Path, end: int) -> Iterator[bytes]:
    """The rows of `path` before position `end`, newest first, without reading the file whole."""
    with path.open("rb") as handle:
        pos, rest = end, b""
        while pos > 0:
            step = min(BACKWARD_STEP_BYTES, pos)
            pos -= step
            handle.seek(pos)
            parts = (handle.read(step) + rest).split(b"\n")
            rest = parts[0]
            for row in reversed(parts[1:]):
                if row.strip():
                    yield row
        if rest.strip():
            yield rest


def last_context_tokens(path: Path) -> int | None:
    """The context amount of the last answer in `path` that carries a `usage` (None when there is none yet)."""
    for raw in _rows_from_the_end(path, end_of_complete_lines(path)):
        if b'"assistant"' not in raw:
            continue
        try:
            amount = context_tokens_of_row(json.loads(raw))
        except ValueError:
            continue
        if amount is not None:
            return amount
    return None


@dataclass(frozen=True)
class Changes:
    """What one look at a record found.

    `present` is whether the file exists; `offset` the position to read from next time; `identity` which file it was
    (`st_dev`, `st_ino`; None when it is not there), to hand back at the next look; `rows` the new whole rows with the
    position at the end of each; `rewound` that the file got shorter than the last position, was replaced by another
    file, or vanished, so that the screen must fetch its history again; `scanned_tokens` the context amount found by
    reading the file's end again (only meaningful when `scanned` is true: at the first look and after a rewind);
    `unreadable` why the file could not be read (None when it could)."""
    present: bool
    offset: int
    identity: tuple[int, int] | None = None
    rows: list[tuple[str, int]] = field(default_factory=list)
    rewound: bool = False
    scanned: bool = False
    scanned_tokens: int | None = None
    unreadable: str | None = None


def look_at_record(path: Path, offset: int | None, was_present: bool, *, identity: tuple[int, int] | None = None,
                   count_tokens: bool = True) -> Changes:
    """Look at `path`, given the position read to last time (None = this is the first look since the backend started)
    and the `identity` the last look returned.

    First look: start from the end of the whole rows, so that a restart does not stream the whole record again; a file
    that is not there yet is read from 0 when it appears. Later: the new whole rows from `offset`; a file shorter than
    `offset`, another file renamed over it (= a program that starts a new conversation in the same path), or a file
    gone, rewinds to 0. A replacement that has already grown past `offset` is caught by its identity, not its size.
    Without `count_tokens` (= a tab whose program says its context amount) the file's end is never read again to count
    it."""
    def counted() -> int | None:
        return last_context_tokens(path) if count_tokens else None

    try:
        stat = path.stat()
        now = (stat.st_dev, stat.st_ino)
        if offset is None:
            return Changes(present=True, offset=end_of_complete_lines(path), identity=now, scanned=True,
                           scanned_tokens=counted())
        if not was_present:
            offset = 0
        rewound = stat.st_size < offset or (identity is not None and identity != now)
        if rewound:
            offset = 0
        rows, new_offset = read_complete_lines_with_pos(path, offset)
        scanned_tokens = counted() if rewound else None
    except FileNotFoundError:
        return Changes(present=False, offset=0, rewound=was_present, scanned=True)
    except OSError as error:
        return Changes(present=was_present, offset=offset or 0, identity=identity, unreadable=str(error))
    return Changes(present=True, offset=new_offset, identity=now, rows=rows, rewound=rewound, scanned=rewound,
                   scanned_tokens=scanned_tokens)


def line_number_at(path: Path, end_position: int) -> int:
    """The 1-based number of the row that ends at `end_position` (= counted from the file, for a log line)."""
    count, remaining = 0, end_position
    with path.open("rb") as handle:
        while remaining > 0:
            chunk = handle.read(min(BACKWARD_STEP_BYTES, remaining))
            if not chunk:
                break
            count += chunk.count(b"\n")
            remaining -= len(chunk)
    return count
