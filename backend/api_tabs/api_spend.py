"""The spend file of an API wallet: what the program that calls the API writes, and what the client shows of it.

The program counts what it spent and rewrites the whole file each time (a temporary file renamed over it):
`{"month": "2026-11", "spent": 123, "limit": 1000, "currency": "JPY", "updated_at": "2026-11-18T12:00:00+09:00"}`.
The client never counts; it reads this file. Only this month's figure is shown, and a file of another month counts as
no figure at all, never as zero. Reading the file blocks: callers run it in a thread. Used by `api_tab_stream.py`
(reads) and `api_tab_rows.py` (shows).
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path


@dataclass(frozen=True)
class Spend:
    """One reading of a spend: a wallet's spend file, or the spend of a tab in a tab list, whose `limit` may be None
    (= the tabs share their wallet's limit)."""
    month: str
    spent: float
    limit: float | None
    currency: str
    updated_at: str | None

    def to_dict(self) -> dict:
        return {"month": self.month, "spent": self.spent, "limit": self.limit, "currency": self.currency,
                "updated_at": self.updated_at}


def _amount(raw: object, field: str) -> float:
    if isinstance(raw, bool) or not isinstance(raw, (int, float)) or raw < 0:
        raise ValueError(f"{field} must be a number that is not negative")
    return raw


def parse_spend(text: str, *, is_limit_optional: bool = False) -> Spend:
    """The reading a spend file's text holds. With `is_limit_optional` the text may leave `limit` out (= a tab's spend in
    a tab list). Raises `ValueError` (with the reason) when the text is not that shape."""
    try:
        raw = json.loads(text)
    except json.JSONDecodeError as error:
        raise ValueError(f"not JSON: {error.msg}") from error
    if not isinstance(raw, dict):
        raise ValueError("not an object")
    month, currency, updated_at = raw.get("month"), raw.get("currency"), raw.get("updated_at")
    if not (isinstance(month, str) and len(month) == 7 and month[4] == "-"):
        raise ValueError("month must be YYYY-MM")
    if not (isinstance(currency, str) and currency):
        raise ValueError("currency must be a text")
    limit = raw.get("limit")
    if limit is not None or not is_limit_optional:
        limit = _amount(limit, "limit")
    return Spend(month=month, spent=_amount(raw.get("spent"), "spent"), limit=limit,
                 currency=currency, updated_at=updated_at if isinstance(updated_at, str) else None)


def this_months(spend: Spend | None, now: datetime) -> Spend | None:
    """`spend` when it is of the month `now` falls in (= the machine's own calendar), else None (= no figure)."""
    return spend if spend is not None and spend.month == now.strftime("%Y-%m") else None


def file_signature(path: Path) -> tuple[int, int, int] | None:
    """(inode, modified time in ns, size) of `path`, None when it cannot be seen: what tells that a small file changed.
    The inode tells a file renamed over the old one even when its size and time come out the same."""
    try:
        stat = os.stat(path)
    except OSError:
        return None
    return stat.st_ino, stat.st_mtime_ns, stat.st_size


def read_spend_file(path: Path) -> Spend:
    """The reading `path` holds. Raises `OSError` when it cannot be read and `ValueError` when it is not a spend file."""
    return parse_spend(path.read_text(encoding="utf-8"))
