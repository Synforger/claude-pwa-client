"""The first line of the client's own notices (the continue message after a move, the message after a limit ended) is
written once and read by everything that tells the operator's words from the client's (`jsonl/jsonl_predicates.py`)."""
from __future__ import annotations

from pathlib import Path

from backend.account_fallback.fallback_envelope import carry_on_envelope
from backend.jsonl.jsonl_predicates import CLIENT_NOTICE_OPENING, CLIENT_OPENINGS, ROLLOVER_OPENING, is_client_message
from backend.limit_resume.resume_envelope import resume_envelope

ROOT = Path(__file__).resolve().parents[3]


def test_both_notices_begin_with_their_own_line_and_not_the_rollover_s():
    for text in (carry_on_envelope("work", "personal"), resume_envelope("personal")):
        assert text.splitlines()[0] == CLIENT_NOTICE_OPENING != ROLLOVER_OPENING
        assert is_client_message(text)


def test_the_line_is_one_the_client_reads_as_not_typed_by_the_operator():
    assert CLIENT_NOTICE_OPENING in CLIENT_OPENINGS
    assert is_client_message(f"\n  {CLIENT_NOTICE_OPENING}\n<limit-resume account=\"a\">\nx\n</limit-resume>")
    assert not is_client_message("Sent by the client, honest")


def test_the_opening_line_is_the_same_everywhere_it_is_written():
    """The backend writes the first line, the screen reads it and the docs tell other tools about it."""
    assert f"'{CLIENT_NOTICE_OPENING}'" in (ROOT / "frontend/src/features/chat/agentMessage.js").read_text()
    assert CLIENT_NOTICE_OPENING in (ROOT / "docs/reference/account-fallback.md").read_text()
    assert CLIENT_NOTICE_OPENING in (ROOT / "docs/reference/limit-resume.md").read_text()
