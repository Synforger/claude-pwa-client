"""Fixtures of the permission window tests: a tab with an empty status, the window state and the kept messages reset, and the
functions the kept messages are typed, looked at and told with put in a recorder."""
from __future__ import annotations

from dataclasses import dataclass, field

import pytest

import backend.permission_window.window_hold as window_hold
import backend.permission_window.window_state as window_state
from backend._common.state import agent_status, sessions_meta

SID = "ses_win"


@dataclass
class Recorder:
    """What the kept messages were typed and told with: the texts typed (each `(text, sender_tab)`), the tabs told, the
    answers the typing gives, whether the tab and its claude are there and which conversation it is in."""
    typed: list = field(default_factory=list)
    told: list = field(default_factory=list)
    answers: list = field(default_factory=list)
    tab_exists: bool = True
    claude_alive: bool = True
    conversation: str | None = "conv-1"


@pytest.fixture(autouse=True)
def recorder(monkeypatch, tmp_path):
    shown = Recorder()

    async def send(session_id, text, sender_tab):
        shown.typed.append((text, sender_tab))
        return shown.answers.pop(0) if shown.answers else {"ok": True}

    async def alive(_session_id):
        return shown.claude_alive

    async def tell(sender_tab, session_id, text, reason):
        shown.told.append((sender_tab, session_id, text, reason))

    monkeypatch.setattr(window_hold, "_wiring", window_hold.Wiring(
        send=send, tab_exists=lambda _sid: shown.tab_exists, claude_alive=alive,
        conversation_of=lambda _sid: shown.conversation, tell_sender=tell))
    monkeypatch.setattr(window_hold, "WINDOW_HOLD_PATH", tmp_path / "window_hold.json")
    monkeypatch.setattr(window_hold, "_kept", {})
    monkeypatch.setattr(window_hold, "_typers", {})
    monkeypatch.setattr(window_hold, "_loaded", True)
    return shown


@pytest.fixture(autouse=True)
def tab(monkeypatch):
    """The tab `SID` with a status that has no window; the window state is put back after the test."""
    monkeypatch.setitem(agent_status, SID, {"pending_plan": None, "pending_permission": None})
    monkeypatch.setitem(sessions_meta, SID, object())
    monkeypatch.setattr(window_state, "_tabs", {})
    monkeypatch.setattr(window_state.jsonl_watcher, "get_jsonl_for", lambda _sid: None)
    return agent_status[SID]


def call_row(tool_use_id: str, name: str, tool_input: dict) -> dict:
    """An assistant row of the record with one `tool_use`."""
    return {"type": "assistant", "message": {"content": [{"type": "tool_use", "id": tool_use_id, "name": name,
                                                          "input": tool_input}]}}


def result_row(tool_use_id: str) -> dict:
    return {"type": "user", "message": {"content": [{"type": "tool_result", "tool_use_id": tool_use_id,
                                                      "content": "ok"}]}}


def decision_row(tool_use_id: str, decision: str = "deny") -> dict:
    return {"type": "attachment", "attachment": {"type": "hook_permission_decision", "decision": decision,
                                                 "toolUseID": tool_use_id, "hookEvent": "PermissionRequest"}}
