"""Samples of what a usage limit leaves in a conversation record, shared by the tests of the cut (`fork/`), of the
record facts (`sleep/`) and of the features that react to a stop (`account_fallback/`, `limit_resume/`)."""
from __future__ import annotations

import json


def limit_stop_row(uuid: str, parent: str | None, timestamp: str = "2026-11-05T10:00:00.000Z", **extra) -> dict:
    """The row Claude Code writes when a usage limit ended a turn. Its shape is that of the API-error row a real record
    holds (an assistant message of the synthetic model with `isApiErrorMessage` and an `error`); the `error` is
    `rate_limit`, which is what Claude Code's own code gives a limit."""
    row = {
        "parentUuid": parent, "isSidechain": False, "type": "assistant", "uuid": uuid, "timestamp": timestamp,
        "message": {"id": f"msg-{uuid}", "model": "<synthetic>", "role": "assistant", "stop_reason": "stop_sequence",
                    "type": "message", "content": [{"type": "text", "text": "You've hit your limit"}]},
        "error": "rate_limit", "isApiErrorMessage": True, "sessionId": "OLD",
    }
    row.update(extra)
    return row


def message_row(uuid: str, parent: str | None, kind: str, content, timestamp: str = "2026-11-05T09:00:00.000Z") -> dict:
    """A user or assistant row; `content` is a text or the list of blocks."""
    return {"parentUuid": parent, "isSidechain": False, "type": kind, "uuid": uuid, "timestamp": timestamp,
            "sessionId": "OLD", "message": {"id": f"msg-{uuid}", "role": kind, "content": content}}


def tool_call(uuid: str, parent: str | None, timestamp: str = "2026-11-05T09:00:00.000Z") -> dict:
    return message_row(uuid, parent, "assistant", [{"type": "tool_use", "id": f"t-{uuid}", "name": "Read", "input": {}}],
                       timestamp)


def tool_result(uuid: str, parent: str | None, call_uuid: str, timestamp: str = "2026-11-05T09:00:01.000Z") -> dict:
    return message_row(uuid, parent, "user", [{"type": "tool_result", "tool_use_id": f"t-{call_uuid}", "content": "ok"}],
                       timestamp)


def stopped_mid_turn(stop_timestamp: str = "2026-11-05T10:00:00.000Z", stop_uuid: str = "lim1") -> list[dict]:
    """A prompt, a tool call, its result, and then the limit: the turn a limit stopped half way."""
    return [
        message_row("u1", None, "user", "please read it"),
        tool_call("a1", "u1"),
        tool_result("u2", "a1", "a1"),
        limit_stop_row(stop_uuid, "u2", stop_timestamp),
    ]


def iso(unix_seconds: float) -> str:
    """The time as a row of a record writes it."""
    from datetime import datetime, timezone  # noqa: PLC0415
    return datetime.fromtimestamp(unix_seconds, timezone.utc).isoformat().replace("+00:00", "Z")


def lines_of(rows: list[dict]) -> list[str]:
    return [json.dumps(row) for row in rows]


def use_accounts(monkeypatch, accounts: dict) -> None:
    """Make the configuration the tests run under hold `accounts` (and otherwise what it held)."""
    import backend._common.config as config  # noqa: PLC0415
    merged = {**config.get_config(), "accounts": accounts}

    def get_config() -> dict:
        return merged
    get_config.cache_clear = lambda: None          # the fixtures of the suite clear the cache of the real function
    monkeypatch.setattr(config, "get_config", get_config)
