"""Watch the conversation record of a tab an ask typed into: for the usage limit that ends the turn without a `Stop`
hook, and for the cancelling of the continuation Claude Code then books. Used by `ask_turn.py`.

Only the rows written after the typing count (`turn_limit.rows_after`): a tab woken for the ask reopens its last
conversation, whose older rows may end in an older limit. While the record stays the same file, only what was added
after the typing is read.
"""
from __future__ import annotations

import asyncio
import json
import time
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import NamedTuple

import backend.jsonl.jsonl_watcher as jsonl_watcher
from backend.ask.turn_limit import TurnEnd, rows_after, turn_end
from backend.jsonl.jsonl_tail import read_complete_lines

#: How often the record is read while an ask waits (= the limit row comes about half a second after the typing)
POLL_SEC = 1.0
#: How long a `Stop` waits for its turn's answer row to reach the record (= the hook can come before the write)
ANSWER_ROW_WAIT_SEC = 2.0
#: How long an Escape waits for Claude Code's notice that the booked continuation was cancelled, and how many tries
CANCEL_WAIT_SEC = 3.0
CANCEL_TRIES = 2
#: How often the record is read again while waiting for a row that is about to come
SHORT_POLL_SEC = 0.2

NOTHING = TurnEnd(has_answer_row=False, limit_message=None, is_booked=False, is_cancelled=False)


class RecordMark(NamedTuple):
    """Where the ask's turn begins: the record and its size when the text was typed, and the time of the typing."""
    path: Path | None
    offset: int
    typed_at: float


def mark(session_id: str) -> RecordMark:
    """The mark to take right before the text is typed. Blocking (the record's size)."""
    path = jsonl_watcher.get_jsonl_for(session_id)
    try:
        offset = path.stat().st_size if path is not None else 0
    except OSError:
        offset = 0
    return RecordMark(path, offset, time.time())


def read_turn(session_id: str, since: RecordMark) -> TurnEnd:
    """What the record says of the turn so far. A record that is another file than at the typing (= the ask started
    or reopened the tab's claude) is read from its start. Blocking."""
    path = jsonl_watcher.get_jsonl_for(session_id)
    if path is None:
        return NOTHING
    lines, _ = read_complete_lines(path, since.offset if path == since.path else 0)
    rows = []
    for line in lines:
        try:
            row = json.loads(line)
        except ValueError:
            continue
        if isinstance(row, dict):
            rows.append(row)
    return turn_end(rows_after(rows, since.typed_at))


async def wait_for_limit(session_id: str, since: RecordMark) -> str:
    """Wait until the turn ends in a usage limit. → the limit row's text. Runs until it is cancelled otherwise."""
    while True:
        end = await asyncio.to_thread(read_turn, session_id, since)
        if end.limit_message is not None:
            return end.limit_message
        await asyncio.sleep(POLL_SEC)


async def settled_turn(session_id: str, since: RecordMark) -> TurnEnd:
    """The turn as the record has it once a `Stop` came, waiting a little for its answer row when it is not written
    yet. A tab with no record has nothing to wait for."""
    deadline = time.monotonic() + ANSWER_ROW_WAIT_SEC
    while True:
        if jsonl_watcher.get_jsonl_for(session_id) is None:
            return NOTHING
        end = await asyncio.to_thread(read_turn, session_id, since)
        if end.has_answer_row or time.monotonic() >= deadline:
            return end
        await asyncio.sleep(SHORT_POLL_SEC)


async def cancel_continuation(session_id: str, since: RecordMark, press_escape: Callable[[], Awaitable[object]],
                              is_stopping: Callable[[], bool]) -> bool | None:
    """Cancel the continuation Claude Code booked at the limit, so that the tab does not carry on with the question
    by itself when the limit resets. → True when its cancelling is in the record, False when it is not after every
    try, None when nothing was booked (= nothing pressed). When the backend is stopping, the first look after the
    first Escape is the last."""
    end = await asyncio.to_thread(read_turn, session_id, since)
    if not end.is_booked:
        return None
    for _ in range(CANCEL_TRIES):
        await press_escape()
        deadline = time.monotonic() + CANCEL_WAIT_SEC
        while time.monotonic() < deadline:
            await asyncio.sleep(SHORT_POLL_SEC)
            if (await asyncio.to_thread(read_turn, session_id, since)).is_cancelled:
                return True
            if is_stopping():
                return False
    return False
