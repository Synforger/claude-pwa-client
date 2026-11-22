"""The `PermissionRequest` hook stands a window up for the screen and pushes it once (`routes/hooks.py`)."""
from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import backend.routes.hooks as hooks_router
from backend._common.state import agent_status
from backend.permission_window import window_state
from backend.tests.routes.test_hooks_router import captured_pushes, fake_agents, fake_bindings  # noqa: F401  (fixtures)

BASH = {"command": "echo LABASK-B1", "description": "Echo LABASK-B1"}


@pytest.fixture
def hook(fake_agents, fake_bindings, captured_pushes, monkeypatch):  # noqa: F811
    """The hooks door with the tab `primary` bound to Claude's conversation `claude-internal-uuid`."""
    fake_bindings("primary", "claude-internal-uuid")
    monkeypatch.setitem(agent_status, "primary", {"pending_plan": None, "pending_permission": None})
    monkeypatch.setattr(window_state, "_tabs", {})
    monkeypatch.setattr(window_state, "_close_listeners", [])
    app = FastAPI()
    app.include_router(hooks_router.router)
    client = TestClient(app)

    def post(event: str, **fields):
        return client.post("/hooks/event", json={"hook_event_name": event, "session_id": "claude-internal-uuid",
                                                 "cwd": fake_agents["cwd"], **fields})
    return post


def test_a_permission_request_stands_a_window_up_and_pushes_it_once(hook, captured_pushes):  # noqa: F811
    reply = hook("PermissionRequest", tool_name="Bash", tool_input=BASH, prompt_id="p1")
    assert reply.json() == {"ok": True, "pushed": "PermissionRequest", "window": 1}
    shown = agent_status["primary"]["pending_permission"]
    assert (shown["tool_name"], shown["input"], shown["count"]) == ("Bash", BASH, 1)
    assert len(captured_pushes) == 1 and "echo LABASK-B1" in captured_pushes[0][0]


def test_two_windows_push_twice_one_each(hook, captured_pushes):  # noqa: F811
    hook("PermissionRequest", tool_name="Bash", tool_input={"command": "echo B1"}, prompt_id="p1")
    hook("PermissionRequest", tool_name="Bash", tool_input={"command": "echo B2"}, prompt_id="p1")
    assert len(captured_pushes) == 2
    assert agent_status["primary"]["pending_permission"]["count"] == 2


def test_the_notification_of_the_same_window_is_not_a_second_push(hook, captured_pushes):  # noqa: F811
    hook("PermissionRequest", tool_name="Bash", tool_input=BASH, prompt_id="p1")
    reply = hook("Notification", message="Claude needs your permission to use Bash")
    assert reply.json() == {"ok": True, "ignored": "permission_window"}
    assert len(captured_pushes) == 1


def test_a_notification_with_no_window_is_pushed_as_before(hook, captured_pushes):  # noqa: F811
    assert hook("Notification", message="Claude needs your permission to use Bash").json() == {
        "ok": True, "pushed": "Notification"}
    assert len(captured_pushes) == 1


@pytest.mark.parametrize("tool", ["AskUserQuestion", "ExitPlanMode"])
def test_a_question_and_a_plan_approval_are_recorded_but_make_no_window_and_no_push(hook, captured_pushes, tool):  # noqa: F811
    reply = hook("PermissionRequest", tool_name=tool, tool_input={}, prompt_id="p1")
    assert reply.json() == {"ok": True, "observed": tool}
    assert agent_status["primary"]["pending_permission"] is None
    assert window_state.is_holding("primary") and not window_state.is_open("primary")
    assert captured_pushes == []


def test_the_hook_answers_nothing_so_the_window_stays_claudes_own(hook):
    reply = hook("PermissionRequest", tool_name="Bash", tool_input=BASH, prompt_id="p1")
    assert "decision" not in reply.json() and "hookSpecificOutput" not in reply.json()


def test_a_stop_and_a_session_start_close_the_window(hook):
    hook("PermissionRequest", tool_name="Bash", tool_input=BASH, prompt_id="p1")
    hook("Stop", last_assistant_message="done", transcript_path="")
    assert agent_status["primary"]["pending_permission"] is None
    hook("PermissionRequest", tool_name="Bash", tool_input=BASH, prompt_id="p2")
    assert window_state.is_open("primary")


def test_the_screen_close_of_the_detector_is_what_ends_a_window_the_record_never_resolves(hook):
    hook("PermissionRequest", tool_name="Bash", tool_input=BASH, prompt_id="p1")
    window_state.note_screen("primary", True)
    window_state.note_screen("primary", False)
    window_state.note_screen("primary", False)
    assert agent_status["primary"]["pending_permission"] is None
