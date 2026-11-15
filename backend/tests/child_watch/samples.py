"""Rows the tests of the child watch share: a child's conversation record that ends in an answer."""
from __future__ import annotations

from backend.tests.limit_samples import iso, message_row


def answer_row(uuid: str, parent: str, at: float) -> dict:
    """An assistant row that answers with one word, written at the time `at` (epoch seconds)."""
    return message_row(uuid, parent, "assistant", [{"type": "text", "text": "done"}], iso(at))
