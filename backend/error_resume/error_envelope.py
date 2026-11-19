"""The message the client types into a tab whose turn a passing API error ended, asking it to carry on, and the words of
the push that tells the operator the client gave up. The first line of the message is the one the client's own
notices begin with, so a reader can tell the operator did not type it; the error's words came from the API or a
gateway, so they are made harmless before they go inside.

Used by `error_patrol.py`.
"""
from __future__ import annotations

from backend.jsonl.jsonl_predicates import API_ERROR_RESUME_TAG as TAG
from backend.jsonl.jsonl_predicates import CLIENT_NOTICE_OPENING as OPENING
from backend.jsonl.jsonl_predicates import plain_attr, plain_text
from backend.sleep.record_facts import ErrorStop


def resume_envelope(stop: ErrorStop, streak: int) -> str:
    """The message that asks the tab to carry on after the API error `stop`; `streak` is how many such messages in a
    row already met an error."""
    words = plain_text(stop.words) or "(no words)"
    return (f'{OPENING}\n<{TAG} error="{plain_attr(stop.error)}" cause="{plain_attr(stop.cause)}" streak="{streak}">\n'
            f"Your last turn ended on an API error, so what you wrote before it may be incomplete. "
            f"Carry on from where it stopped.\n"
            f"> {words}\n"
            f"</{TAG}>")


def gave_up_words(stop: ErrorStop, sent_count: int) -> str:
    """The body of the push that tells the operator the client stopped carrying the tab on after `sent_count`
    messages."""
    return f"Stopped on an API error after {sent_count} message(s) to carry on: {stop.words}"
