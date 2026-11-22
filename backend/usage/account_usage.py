"""Which row of the rate-limit log says what an account's usage is now. Pure: it compares the rows it is given.

Every session writes a row whenever it redraws its status line, with the figures it last received, so the newest row
of an account can be the old figures of a quiet session. A row therefore counts for the account only when it brings
news: figures that differ from the row the same session wrote before it, or a window that is gone before it was due to
reset (= the plan has no such window any more). A window that is gone once its reset time has passed is no news:
Claude Code leaves it out from then on. Used by `usage.py`.
"""
from __future__ import annotations

from backend.usage.limit_state import WINDOWS


def _is_figure(value: object) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def has_usage(row: dict) -> bool:
    """Whether the row says the usage of any window."""
    return any(_is_figure(row.get(pct_field)) for pct_field, _ in WINDOWS)


def _has_reset(before: dict, reset_field: str, at: object) -> bool:
    """Whether the window of `before` had reset by `at`, the time of a later row (the same second counts as reset)."""
    resets_at = before.get(reset_field)
    return _is_figure(resets_at) and resets_at > 0 and _is_figure(at) and at >= resets_at


def is_news(row: dict, before: dict | None) -> bool:
    """Whether `row` becomes the account's usage. `before` is the row the same session wrote before it on the same
    account, or the account's usage when the session wrote none; None when there is neither. The figures are never
    compared by size: a usage that went down is news like any other."""
    if not has_usage(row):
        return False
    if before is None:
        return True
    for pct_field, reset_field in WINDOWS:
        new, old = row.get(pct_field), before.get(pct_field)
        if _is_figure(new):
            if (new, row.get(reset_field)) != (old, before.get(reset_field)):
                return True
        elif _is_figure(old) and not _has_reset(before, reset_field, row.get("timestamp")):
            return True
    return False


def account_row(row: dict, account_id: str) -> dict:
    """The copy of `row` that stands for the account's usage. It names no session, so whoever looks for a session's
    newest row (its context and model) never takes it."""
    copy = {key: value for key, value in row.items() if key != "session_id"}
    copy["account_id"] = account_id
    return copy
