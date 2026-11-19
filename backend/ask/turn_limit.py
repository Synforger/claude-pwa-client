"""Whether the turn an ask typed ended in a usage limit, read from the rows of the tab's conversation record. Pure:
it takes rows already parsed and reads no file. Used by `limit_watch.py`.

Claude Code ends a turn that hits a usage limit with an API-error row (`fork.is_limit_stop_row`) and no `Stop`
hook, then books its own continuation for the reset with a notice row, which an Escape cancels.
"""
from __future__ import annotations

from typing import NamedTuple

from backend.fork.fork import is_limit_stop_row
from backend.jsonl.jsonl_tail import parse_jsonl_timestamp

#: The words of Claude Code's notices: the continuation it booked at a limit, and the cancelling of it
BOOKED_WORDS = "continuing automatically"
CANCELLED_WORDS = "continue cancelled"


class TurnEnd(NamedTuple):
    """What the rows after the typing say about the turn."""
    has_answer_row: bool         # an assistant row was written after the typing
    limit_message: str | None    # the text of the limit row the turn ended in; None when it did not
    is_booked: bool              # Claude Code booked its continuation for the reset
    is_cancelled: bool           # that continuation was cancelled


def rows_after(rows: list[dict], typed_at: float) -> list[dict]:
    """The rows written at or after `typed_at` (= the rows of an older conversation a tab was reopened in are left
    out). A row with no time is kept: it can only be one just written."""
    kept = []
    for row in rows:
        stamp = parse_jsonl_timestamp(row.get("timestamp"))
        if stamp is None or stamp >= typed_at:
            kept.append(row)
    return kept


def turn_end(rows: list[dict]) -> TurnEnd:
    """Read the rows written after the typing."""
    last_answer: dict | None = None
    is_booked = is_cancelled = False
    for row in rows:
        if row.get("type") == "assistant":
            last_answer = row
        elif row.get("type") == "system":
            content = str(row.get("content") or "")
            is_booked = is_booked or BOOKED_WORDS in content
            is_cancelled = is_cancelled or CANCELLED_WORDS in content
    limit_message = _text_of(last_answer) if last_answer is not None and is_limit_stop_row(last_answer) else None
    return TurnEnd(last_answer is not None, limit_message, is_booked, is_cancelled)


def _text_of(row: dict) -> str:
    content = (row.get("message") or {}).get("content")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(block.get("text", "") for block in content if isinstance(block, dict))
    return ""
