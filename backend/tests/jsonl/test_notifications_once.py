"""An Agent or Workflow completion is pushed once, though Claude Code writes its notice in two rows (= the queueing
`queue-operation` row and the `user` row of the turn it starts) (`backend/jsonl/notifications.py`)."""
from __future__ import annotations

import time
from datetime import datetime, timezone

import pytest

from backend.jsonl import notifications
from backend.tests.async_run import run

NOTICE = ("<task-notification>\n<task-id>a1b2c3</task-id>\n<tool-use-id>toolu_x</tool-use-id>\n"
          "<status>completed</status>\n<summary>Agent \"Review the design\" finished</summary>\n</task-notification>")


@pytest.fixture
def pushed(monkeypatch):
    sent = []

    async def push(body: str, title: str, session_id: str) -> None:
        sent.append((session_id, body))

    monkeypatch.setattr(notifications, "broadcast_push", push)
    monkeypatch.setattr(notifications, "notification_title_for", lambda session_id: "tab")
    monkeypatch.setattr(notifications, "_pushed_keys", {})
    return sent


def _now() -> str:
    return datetime.fromtimestamp(time.time(), timezone.utc).isoformat().replace("+00:00", "Z")


async def _both_rows(session_id: str) -> None:
    notifications.maybe_push_blockers(session_id, {"type": "queue-operation", "operation": "enqueue",
                                                   "timestamp": _now(), "content": NOTICE})
    notifications.maybe_push_blockers(session_id, {"type": "user", "timestamp": _now(),
                                                   "message": {"role": "user", "content": NOTICE}})


def test_the_two_rows_of_one_completion_push_once(pushed):
    run(_both_rows("ses_a"))
    assert pushed == [("ses_a", '🤖 Agent "Review the design" finished')]


def test_the_same_notice_in_another_tab_is_pushed_there_too(pushed):
    run(_both_rows("ses_a"))
    run(_both_rows("ses_b"))
    assert [session_id for session_id, _ in pushed] == ["ses_a", "ses_b"]
