"""The message the client sends a parent tab about a child that stopped without reporting. The first line is the one the
client's own notices begin with, so a reader can tell the operator did not type it; the block names the child, its
title and why it stopped.

Used by `watch_patrol.py`.
"""
from __future__ import annotations

from backend.child_watch.watch_judgement import LIMIT
from backend.jsonl.jsonl_predicates import CLIENT_NOTICE_OPENING as OPENING

TAG = "child-stopped"

_BODY = {
    LIMIT: ("A usage limit stopped this child before it reported. Once the limit is over it is told to carry on "
            "(by Claude Code itself, or by the client when the child's claude was started again since), so it needs "
            "nothing from you unless it stays stopped."),
}
_IDLE_BODY = ("This child is waiting for input and has not reported. It stopped without running `tabs report`: "
              "read the end of its conversation, then send it a message or close it.")


def _attr(value: str) -> str:
    return value.replace('"', "'").replace("\n", " ")


def child_stopped_envelope(child_id: str, title: str, reason: str) -> str:
    """The message that tells a parent tab its child `child_id` (named `title`) stopped for `reason` (`LIMIT` or
    `IDLE` of `watch_judgement.py`)."""
    return (f'{OPENING}\n<{TAG} child="{_attr(child_id)}" title="{_attr(title)}" reason="{_attr(reason)}">\n'
            f"{_BODY.get(reason, _IDLE_BODY)}\n"
            f"</{TAG}>")
