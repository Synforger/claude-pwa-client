"""What counts as a typed text being taken (`terminal/confirm.py` `wait_taken_row`): a row of a person's prompt, or the
row of that text being queued while Claude answers. The rows are shaped as Claude Code writes them."""
from __future__ import annotations

import json

from backend.terminal import confirm
from backend.tests.async_run import run

MESSAGE = ("Message from another session, relayed by the client (the operator did not type this):\n"
           "<agent-message from=\"x\" session=\"ses_x\">\nPlease look.\n</agent-message>")
WAIT_SEC = 0.3


def _row(**fields) -> str:
    return json.dumps(fields) + "\n"


def _prompt(text: str) -> str:
    return _row(type="user", message={"role": "user", "content": text}, uuid="u1")


def _enqueue(content: str) -> str:
    return _row(type="queue-operation", operation="enqueue", timestamp="2026-11-09T10:18:20.886Z", content=content)


def _taken(record, initial_pos: int, text: str = MESSAGE) -> bool:
    return run(confirm.wait_taken_row(record, initial_pos, WAIT_SEC, text))


def test_a_prompt_row_after_the_typing_is_taken(tmp_path):
    record = tmp_path / "r.jsonl"
    record.write_text(_prompt(MESSAGE))
    assert _taken(record, 0) is True


def test_a_text_queued_while_claude_answers_is_taken(tmp_path):
    record = tmp_path / "r.jsonl"
    record.write_text(_enqueue(f"<pasted_content id=\"cc3c\">\n{MESSAGE}\n</pasted_content>"))
    assert _taken(record, 0) is True


def test_another_queued_text_is_not_this_one(tmp_path):
    record = tmp_path / "r.jsonl"
    record.write_text(_enqueue("<task-notification>\n<task-id>b1</task-id>\n</task-notification>"))
    assert _taken(record, 0) is False


def test_rows_written_before_the_typing_do_not_count(tmp_path):
    record = tmp_path / "r.jsonl"
    before = _prompt("earlier words") + _enqueue(MESSAGE)
    record.write_text(before)
    assert _taken(record, len(before.encode())) is False


def test_nothing_written_is_not_taken(tmp_path):
    record = tmp_path / "r.jsonl"
    record.write_text("")
    assert _taken(record, 0) is False
