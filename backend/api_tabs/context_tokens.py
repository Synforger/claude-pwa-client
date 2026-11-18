"""How much of the context an API tab's conversation holds, counted from one record row.

It is the input side of the last answer: the three input counts of the `usage` a Messages API answer carries. A row
without `usage` says nothing (None, never 0). Pure: no file is read here. Used by `api_tab_record.py` and
`api_tab_stream.py`.
"""
from __future__ import annotations

#: The `usage` counts that make up what the next call has to carry in.
INPUT_COUNTS = ("input_tokens", "cache_read_input_tokens", "cache_creation_input_tokens")


def _count(raw: object) -> int:
    return raw if isinstance(raw, int) and not isinstance(raw, bool) and raw >= 0 else 0


def context_tokens_of_row(row: object) -> int | None:
    """The context amount an assistant row reports, None for a row that is not an assistant row with a `usage`."""
    if not isinstance(row, dict) or row.get("type") != "assistant":
        return None
    message = row.get("message")
    usage = message.get("usage") if isinstance(message, dict) else None
    if not isinstance(usage, dict):
        return None
    return sum(_count(usage.get(field)) for field in INPUT_COUNTS)
