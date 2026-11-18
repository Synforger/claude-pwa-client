"""The rows a Messages API conversation leaves in a record, and the helpers that write them, for the API tab tests (the
`api_env` fixture that uses them is in `backend/tests/conftest.py`)."""
from __future__ import annotations

import json

import backend._common.config as config_mod
from backend.tests.conftest import _TEST_CONFIG

TAB_ID = "api_support-bot"


def user_row(uuid: str, text: str) -> dict:
    return {"type": "user", "uuid": uuid, "timestamp": "2026-11-18T12:00:00.000Z",
            "message": {"role": "user", "content": text}}


def assistant_row(uuid: str, message_id: str, text: str, usage: dict | None = None, content: list | None = None,
                  stop_reason: str = "end_turn") -> dict:
    message = {"id": message_id, "role": "assistant", "model": "claude-sonnet-5-5",
               "content": content or [{"type": "text", "text": text}], "stop_reason": stop_reason}
    if usage is not None:
        message["usage"] = usage
    return {"type": "assistant", "uuid": uuid, "timestamp": "2026-11-18T12:00:01.000Z", "message": message}


def tool_use_row(uuid: str, message_id: str, tool_id: str) -> dict:
    return assistant_row(uuid, message_id, "", stop_reason="tool_use",
                         content=[{"type": "tool_use", "id": tool_id, "name": "lookup", "input": {}}])


def tool_result_row(uuid: str, tool_id: str) -> dict:
    return {"type": "user", "uuid": uuid, "timestamp": "2026-11-18T12:00:02.000Z",
            "message": {"role": "user", "content": [{"type": "tool_result", "tool_use_id": tool_id, "content": "found"}]}}


def append(path, *rows: dict, partial: str = "") -> None:
    """Add whole rows to a record, then `partial` (= a row still being written, with no newline)."""
    with path.open("a", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row) + "\n")
        handle.write(partial)


def write_config(env, **sections) -> None:
    """Replace the configuration the backend reads, and make it read it again (= what `reload_config` does)."""
    env.config_path.write_text(json.dumps({**_TEST_CONFIG, **sections}))
    config_mod.get_config.cache_clear()
