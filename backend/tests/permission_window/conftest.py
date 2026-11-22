"""Fixtures of the permission window tests: a tab with an empty status, and the window state and the kept texts reset."""
from __future__ import annotations

import pytest

import backend.permission_window.window_hold as window_hold
import backend.permission_window.window_state as window_state
from backend._common.state import agent_status

SID = "ses_win"


@pytest.fixture(autouse=True)
def tab(monkeypatch):
    """The tab `SID` with a status that has no window, and nothing kept; the state is put back after the test."""
    monkeypatch.setitem(agent_status, SID, {"pending_plan": None, "pending_permission": None})
    monkeypatch.setattr(window_state, "_tabs", {})
    monkeypatch.setattr(window_state, "_close_listeners", [])
    monkeypatch.setattr(window_hold, "_kept", {})
    monkeypatch.setattr(window_hold, "_typers", {})
    monkeypatch.setattr(window_hold, "_sender", None)
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
