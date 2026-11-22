"""The `PermissionRequest` hook gives the client the input a window shows and pushes it once (`routes/hooks.py`). It is no
evidence that a window is open: the screen says that (`permission_window/window_state.py`)."""
from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import backend.routes.hooks as hooks_router
from backend._common.state import agent_status
from backend.permission_window import window_state
from backend.permission_window.window_screen import read_screen
from backend.tests.permission_window import screens
from backend.tests.permission_window.conftest import call_row
from backend.tests.routes.test_hooks_router import captured_pushes, fake_agents, fake_bindings  # noqa: F401  (fixtures)

BASH = {"command": "echo LABASK-B1", "description": "Echo LABASK-B1"}


@pytest.fixture
def hook(fake_agents, fake_bindings, captured_pushes, monkeypatch):  # noqa: F811
    """The hooks door with the tab `primary` bound to Claude's conversation `claude-internal-uuid`; the hook is sent with the
    tab's id in the header, as the tab's own Claude does (`as_tab` says another)."""
    fake_bindings("primary", "claude-internal-uuid")
    monkeypatch.setitem(agent_status, "primary", {"pending_plan": None, "pending_permission": None})
    monkeypatch.setattr(window_state, "_tabs", {})
    monkeypatch.setattr(window_state.jsonl_watcher, "get_jsonl_for", lambda _sid: None)
    app = FastAPI()
    app.include_router(hooks_router.router)
    client = TestClient(app)

    def post(event: str, as_tab: str | None = "primary", **fields):
        headers = {"x-pwa-sid": as_tab} if as_tab else {}
        return client.post("/hooks/event", headers=headers, json={
            "hook_event_name": event, "session_id": "claude-internal-uuid", "cwd": fake_agents["cwd"], **fields})
    return post


def the_call_and_the_window_on_the_screen(command="echo LABASK-B1"):
    window_state.fold_row("primary", call_row("toolu_1", "Bash", {"command": command}))
    window_state.note_screen("primary", read_screen(screens.approval(command)))


def test_a_permission_request_keeps_the_input_and_pushes_it_once(hook, captured_pushes):  # noqa: F811
    reply = hook("PermissionRequest", tool_name="Bash", tool_input=BASH, prompt_id="p1")
    assert reply.json() == {"ok": True, "pushed": "PermissionRequest", "window": 1}
    assert len(captured_pushes) == 1 and "echo LABASK-B1" in captured_pushes[0][0]
    assert agent_status["primary"]["pending_permission"] is None      # the screen has not shown a window
    the_call_and_the_window_on_the_screen()
    shown = agent_status["primary"]["pending_permission"]
    assert (shown["tool_name"], shown["input"], shown["count"]) == ("Bash", BASH, 1)


def test_two_windows_push_twice_one_each(hook, captured_pushes):  # noqa: F811
    hook("PermissionRequest", tool_name="Bash", tool_input={"command": "echo B1"}, prompt_id="p1")
    hook("PermissionRequest", tool_name="Bash", tool_input={"command": "echo B2"}, prompt_id="p1")
    assert len(captured_pushes) == 2


def test_f5_a_hook_from_a_tab_other_than_the_one_the_conversation_is_bound_to_is_not_taken(hook, captured_pushes):  # noqa: F811
    reply = hook("PermissionRequest", as_tab="another-tab", tool_name="Bash", tool_input=BASH, prompt_id="p1")
    assert reply.json() == {"ok": True, "ignored": "not_this_tabs_conversation"}
    assert window_state.current_window("primary") is None and captured_pushes == []


def test_f5_a_hook_with_no_tab_in_the_header_is_not_taken(hook, captured_pushes):  # noqa: F811
    reply = hook("PermissionRequest", as_tab=None, tool_name="Bash", tool_input=BASH, prompt_id="p1")
    assert reply.json()["ignored"] in ("not_this_tabs_conversation", "non_pwa_session")
    assert window_state.current_window("primary") is None and captured_pushes == []


def test_a_hook_whose_call_the_record_has_answered_already_makes_nothing(hook, captured_pushes):  # noqa: F811
    from backend.tests.permission_window.conftest import result_row
    window_state.fold_row("primary", call_row("toolu_1", "Bash", BASH))
    window_state.fold_row("primary", result_row("toolu_1"))
    assert hook("PermissionRequest", tool_name="Bash", tool_input=BASH, prompt_id="p1").json() == {
        "ok": True, "ignored": "already_resolved"}
    assert captured_pushes == []


def test_the_notification_of_the_same_window_is_not_a_second_push(hook, captured_pushes):  # noqa: F811
    hook("PermissionRequest", tool_name="Bash", tool_input=BASH, prompt_id="p1")
    the_call_and_the_window_on_the_screen()
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
    assert window_state.current_window("primary") is None and agent_status["primary"]["pending_permission"] is None
    assert captured_pushes == []


def test_the_hook_answers_nothing_so_the_window_stays_claudes_own(hook):
    reply = hook("PermissionRequest", tool_name="Bash", tool_input=BASH, prompt_id="p1")
    assert "decision" not in reply.json() and "hookSpecificOutput" not in reply.json()


def test_a_stop_closes_what_the_client_remembers_of_the_turn(hook):
    hook("PermissionRequest", tool_name="Bash", tool_input=BASH, prompt_id="p1")
    the_call_and_the_window_on_the_screen()
    hook("Stop", last_assistant_message="done", transcript_path="")
    assert window_state.current_window("primary") is None
