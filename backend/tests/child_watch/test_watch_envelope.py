"""The message to a parent about a child that stopped (`child_watch/watch_envelope.py`)."""
from __future__ import annotations

from backend.child_watch.watch_envelope import TAG, child_stopped_envelope
from backend.child_watch.watch_judgement import IDLE, LIMIT
from backend.jsonl.jsonl_predicates import CLIENT_NOTICE_OPENING, is_client_message


def test_the_first_line_is_the_one_of_the_clients_own_notices():
    text = child_stopped_envelope("ses_c", "Build the parser", IDLE)
    assert text.splitlines()[0] == CLIENT_NOTICE_OPENING and is_client_message(text)


def test_the_block_names_the_child_its_title_and_the_reason():
    text = child_stopped_envelope("ses_c", 'Say "hi"\nnow', LIMIT)
    assert f"<{TAG} child=\"ses_c\" title=\"Say 'hi' now\" reason=\"limit\">" in text and text.rstrip().endswith(f"</{TAG}>")


def test_a_limit_says_claude_code_carries_on_by_itself_and_idle_says_it_waits_without_a_report():
    assert "reservation to carry on by itself once the limit is over" in child_stopped_envelope("c", "t", LIMIT)
    idle = child_stopped_envelope("c", "t", IDLE)
    assert "waiting for input" in idle and "has not reported" in idle and "usage limit" not in idle
