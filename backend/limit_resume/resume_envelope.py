"""The message the client sends a tab whose turn a usage limit stopped, once the limit is over. The first line is the one
the client's own notices begin with, so a reader can tell the operator did not type it.

Used by `resume_patrol.py`.
"""
from __future__ import annotations

from backend.jsonl.jsonl_predicates import CLIENT_NOTICE_OPENING as OPENING

TAG = "limit-resume"


def _attr(value: str) -> str:
    return value.replace('"', "'").replace("\n", " ")


def resume_envelope(account: str) -> str:
    """The message that asks a tab to carry on now that the usage limit of `account` is over."""
    return (f'{OPENING}\n<{TAG} account="{_attr(account)}">\n'
            f"The usage limit has ended. Carry on with the work you were doing before it stopped.\n"
            f"</{TAG}>")
