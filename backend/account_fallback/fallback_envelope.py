"""The message the client sends a tab that a usage limit stopped, once it has moved the tab to another account. The
first line is the one the client's own notices begin with, so a reader can tell the operator did not type it; the
block names the move and the reason.

Used by `fallback_patrol.py`.
"""
from __future__ import annotations

from backend.jsonl.jsonl_predicates import CLIENT_NOTICE_OPENING as OPENING

TAG = "account-move"
LIMIT = "limit"


def _attr(value: str) -> str:
    return value.replace('"', "'").replace("\n", " ")


def carry_on_envelope(from_account: str, to_account: str, reason: str = LIMIT) -> str:
    """The message that asks a tab, moved because its work was stopped, to carry on."""
    return (f'{OPENING}\n<{TAG} from="{_attr(from_account)}" to="{_attr(to_account)}" reason="{_attr(reason)}">\n'
            f"A usage limit stopped this session, so the client moved it to another account. "
            f"Carry on with the work you were doing before it stopped.\n"
            f"</{TAG}>")
