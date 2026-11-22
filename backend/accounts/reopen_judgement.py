"""Whether a conversation record can be reopened by another account exactly as it is, when the accounts keep their
records in one folder. Pure: it takes the record's text and answers, and reads no file.

A record is reopened as it is when nothing in it would be cut off by the move: the file ends in a whole line, and the
last row of the conversation (the rows a usage limit wrote left out) is the row the move would cut at anyway
(`fork.fork.latest_clean_fork_point`, or the end of the turn the limit stopped). A call that has no answer yet, a row
that is not finished and a turn that is still going all fail that, and the move then writes the conversation up to its
cut as a new session (`fork.lineage.write_lineage`).

Used by `shared_reopen.py`.
"""
from __future__ import annotations

import json

from backend.fork.fork import is_limit_stop_row, latest_clean_fork_point, latest_cut_through_tool_results
from backend.fork.lineage import LineageCut
from backend.jsonl.jsonl_tail import split_jsonl_text


def _last_conversation_row(lines: list[str]) -> str | None:
    """The uuid of the last user or assistant row of the main conversation, leaving out the rows a usage limit wrote."""
    last: str | None = None
    for raw in lines:
        try:
            row = json.loads(raw)
        except (json.JSONDecodeError, ValueError):
            continue
        if not isinstance(row, dict) or is_limit_stop_row(row):
            continue
        if row.get("type") in ("user", "assistant") and row.get("uuid") and not row.get("isSidechain") \
                and not row.get("isMeta"):
            last = row["uuid"]
    return last


def reopens_as_is(text: str, cut: LineageCut) -> bool:
    """Whether the record whose whole text is `text` can be opened again as it is: it ends in a whole line, and its last
    conversation row is where `cut` would cut it."""
    if not text.endswith("\n"):
        return False
    lines = split_jsonl_text(text)
    cut_at = latest_cut_through_tool_results(lines) if cut is LineageCut.THROUGH_TOOL_RESULTS \
        else latest_clean_fork_point(lines)
    return cut_at is not None and cut_at == _last_conversation_row(lines)
