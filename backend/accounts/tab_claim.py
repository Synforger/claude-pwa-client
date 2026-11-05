"""Keeps two features of the client from working on the same tab at once: the account fallback and the limit resume
each look at tabs on their own interval and may both find the same tab wanting a hand. A tab is claimed for the
length of one piece of work; a feature that finds it claimed leaves it for its next look.

Used by `account_fallback/fallback_patrol.py` and `limit_resume/resume_patrol.py`.
"""
from __future__ import annotations

from contextlib import contextmanager
from typing import Iterator

# The tabs being worked on. The backend runs on one event loop, so a set needs no lock.
_claimed: set[str] = set()


@contextmanager
def claimed(session_id: str) -> Iterator[bool]:
    """Claim the tab for the body of the `with`; yields False (and claims nothing) when it is claimed already."""
    if session_id in _claimed:
        yield False
        return
    _claimed.add(session_id)
    try:
        yield True
    finally:
        _claimed.discard(session_id)
