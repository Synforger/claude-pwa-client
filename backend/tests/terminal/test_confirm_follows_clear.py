"""A slash command that opens a new conversation (`/clear`) is confirmed from the new record, where Claude Code writes
its `<command-name>` row (`backend/terminal/confirm.py`): the confirm does not wait out its time on the old record."""
from __future__ import annotations

import json
import time

from backend.terminal import confirm as confirm_mod
from backend.tests.async_run import run

CLEAR_ROWS = [
    {"type": "user", "message": {"role": "user", "content": "<command-name>/clear</command-name>\n"
                                                             "<command-message>clear</command-message>"}},
]


def _write(path, rows) -> None:
    path.write_text("".join(json.dumps(row) + "\n" for row in rows))


def test_a_clear_is_confirmed_from_the_record_it_opened(tmp_path, monkeypatch):
    old, new = tmp_path / "old.jsonl", tmp_path / "new.jsonl"
    _write(old, [{"type": "user", "message": {"role": "user", "content": "an earlier question"}}])
    _write(new, CLEAR_ROWS)
    monkeypatch.setattr(confirm_mod, "jsonl_path_for_session", lambda session_id: new)
    started = time.monotonic()
    result = run(confirm_mod._confirm_after_send("ses_x", "/clear", old, old.stat().st_size, True))
    assert result == {"ok": True, "confirmed": True}
    assert time.monotonic() - started < 1.0


def test_a_prompt_is_not_counted_in_another_record(tmp_path, monkeypatch):
    old, new = tmp_path / "old.jsonl", tmp_path / "new.jsonl"
    old.write_text("")
    _write(new, [{"type": "user", "message": {"role": "user", "content": "hello"}}])
    monkeypatch.setattr(confirm_mod, "jsonl_path_for_session", lambda session_id: new)
    monkeypatch.setattr(confirm_mod, "CONFIRM_TIMEOUT_SEC", 0.2)
    result = run(confirm_mod._confirm_after_send("ses_x", "hello", old, 0, False))
    assert result == {"ok": True, "confirmed": False}
