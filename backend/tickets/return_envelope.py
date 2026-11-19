"""The message the client sends the tab that asked for a ticket first, when the tab that held it was closed and the ticket came
back to it. The first line is the one the client's own notices begin with, so a reader can tell the operator did not type it.

Used by `ticket_return.py`.
"""
from __future__ import annotations

from backend.jsonl.jsonl_predicates import CLIENT_NOTICE_OPENING as OPENING

TAG = "ticket-returned"


def returned_text(ticket: str) -> str:
    """The one line the tab is told."""
    return f"票 {ticket} を持っていたタブが閉じられたので、 あなたに戻りました"


def returned_envelope(ticket: str) -> str:
    """The message that tells the tab the ticket `ticket` (= an id, which is safe to write in a tag) is its own again."""
    return f'{OPENING}\n<{TAG} ticket="{ticket}">\n{returned_text(ticket)}\n</{TAG}>'
