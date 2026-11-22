"""A slow tmux or process table does not stop the event loop, and moving those calls to threads keeps what their
blocking gave for free: keys reach a tab in the order they were asked for, and one launch is typed per shell.

No tmux and no claude run: `subprocess.run` is replaced by one that notes whether the event loop's thread waited on it.
"""
from __future__ import annotations

import asyncio
import subprocess
import time
from types import SimpleNamespace

import pytest

import backend.routes.agent_messages as agent_messages
import backend.terminal.first_message as first_message
import backend.terminal.input_ready as input_ready
import backend.terminal.routes as routes
import backend.terminal.runner as runner
from backend._common.state import SessionDef

SID = "ses_keys"
SLOW_SEC = 0.05
TAB_COUNT = 30


def _waits_on_the_loop() -> bool:
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return False
    return True


@pytest.fixture
def tmux(monkeypatch) -> SimpleNamespace:
    """A slow tmux: what it was asked, and the calls the event loop waited on."""
    seen = SimpleNamespace(calls=[], on_loop=[])

    def run(argv, *_args, **options):
        seen.calls.append(" ".join(argv))
        if _waits_on_the_loop():
            seen.on_loop.append(" ".join(argv))
        time.sleep(SLOW_SEC)
        return subprocess.CompletedProcess(argv, 0, "" if options.get("text") else b"", "")

    monkeypatch.setattr(runner, "USE_TMUX_WRAP", True)
    monkeypatch.setattr(runner.subprocess, "run", run)
    monkeypatch.setattr(runner, "TWO_STAGE_ENTER_DELAY_SEC", 0)
    monkeypatch.delenv("CPC_E2E", raising=False)
    return seen


@pytest.fixture
def tab(monkeypatch, isolated_state) -> SessionDef:
    meta = SessionDef(id=SID, agent_id="agent_a", title="keys", created_at=0)
    isolated_state.sessions_meta[SID] = meta
    monkeypatch.setattr(routes, "_require_session", lambda _sid: None)
    monkeypatch.setattr(routes, "jsonl_path_for_session", lambda _sid: None)
    monkeypatch.setattr(routes, "stream_states", {})
    monkeypatch.setattr(routes, "_send_locks", {})
    monkeypatch.delenv("CPC_E2E", raising=False)
    input_ready.forget(SID)
    yield meta
    input_ready.forget(SID)
    first_message._held.pop(SID, None)


async def _nothing(*_args, **_options) -> None:
    return None


@pytest.mark.parametrize("route", ["get_local_tabs", "get_tabs_for_peer"])
def test_a_list_of_tabs_is_one_look_taken_off_the_loop(route, tmux, isolated_state, monkeypatch):
    for at in range(TAB_COUNT):
        isolated_state.sessions_meta[f"ses_{at}"] = SessionDef(id=f"ses_{at}", agent_id="agent_a", title=str(at),
                                                               created_at=0)
    monkeypatch.setattr(agent_messages, "require_this_machine", lambda *_args: None)
    monkeypatch.setattr(agent_messages, "require_peer", lambda _request: ("other", {}))
    monkeypatch.setattr(agent_messages, "allowed_for_peer", lambda *_args: True)
    monkeypatch.setattr(agent_messages, "running_claudes", dict)
    rows = asyncio.run(getattr(agent_messages, route)(None))["tabs"]
    assert len(rows) == TAB_COUNT
    assert tmux.on_loop == []
    assert len(tmux.calls) == 1


@pytest.mark.parametrize("payload", [
    pytest.param({"key": "Up"}, id="a key"),
    pytest.param({"text": "2"}, id="text without Enter"),
    pytest.param({"text": "one line", "enter": True}, id="a body"),
    pytest.param({"text": "two\nlines", "enter": True}, id="a body of two lines"),
])
def test_typing_never_makes_the_loop_wait_for_tmux(payload, tmux, tab, monkeypatch):
    monkeypatch.setattr(routes, "launch_with_first_message", _nothing)
    assert asyncio.run(routes.pty_send(SID, payload, None))["ok"]
    assert tmux.calls
    assert tmux.on_loop == []


def test_the_stop_button_never_makes_the_loop_wait_for_tmux(tmux, tab, monkeypatch):
    async def settled(_sid, _sent):
        return routes._Escaped(stopped=True, restored=False)

    monkeypatch.setattr(routes, "_escape_settled", settled)

    async def stop() -> bool:
        result = await routes.pty_send(SID, {"key": "Escape"}, None)
        await routes._stop_clears.pop(SID)
        return result["ok"]

    assert asyncio.run(stop())
    assert tmux.on_loop == []


def _record_keys(monkeypatch, slow: str) -> list[str]:
    typed: list[str] = []

    def keys(_sid, text=None, key=None, enter=False):
        name = key or text or "Enter"
        if name == slow:
            time.sleep(SLOW_SEC * 3)
        typed.append(name)
        return True

    monkeypatch.setattr(routes, "tmux_send_keys", keys)
    monkeypatch.setattr(runner, "tmux_send_keys", keys)
    return typed


def test_keys_reach_the_tab_in_the_order_they_were_asked_for(tab, monkeypatch):
    typed = _record_keys(monkeypatch, slow="Up")

    async def press() -> None:
        await asyncio.gather(*(routes.pty_send(SID, {"key": key}, None) for key in ("Up", "Down", "Tab")))

    asyncio.run(press())
    assert typed == ["Up", "Down", "Tab"]


def test_a_cancelled_key_is_finished_before_the_next_one(tab, monkeypatch):
    typed = _record_keys(monkeypatch, slow="Up")

    async def press() -> None:
        first = asyncio.create_task(routes.pty_send(SID, {"key": "Up"}, None))
        await asyncio.sleep(SLOW_SEC)
        first.cancel()
        await routes.pty_send(SID, {"key": "Down"}, None)

    asyncio.run(press())
    assert typed == ["Up", "Down"]


def test_a_body_sent_during_a_slow_stop_waits_until_the_stop_settled(tab, monkeypatch):
    typed = _record_keys(monkeypatch, slow="Escape")

    async def settled(_sid, _sent):
        await asyncio.sleep(SLOW_SEC)
        typed.append("settled")
        return routes._Escaped(stopped=True, restored=False)

    monkeypatch.setattr(routes, "_escape_settled", settled)
    monkeypatch.setattr(routes, "read_input_box", lambda _sid: "")
    monkeypatch.setattr(routes, "wipe_input_line", lambda _sid: typed.append("wipe"))
    monkeypatch.setattr(runner, "wipe_input_line", lambda _sid: typed.append("wipe"))
    monkeypatch.setattr(runner, "TWO_STAGE_ENTER_DELAY_SEC", 0)
    monkeypatch.setattr(routes, "launch_with_first_message", _nothing)

    async def stop_then_send() -> None:
        stop = asyncio.create_task(routes.pty_send(SID, {"key": "Escape"}, None))
        await asyncio.sleep(SLOW_SEC)
        await routes.pty_send(SID, {"text": "next", "enter": True}, None)
        await stop
        await routes._stop_clears.pop(SID)

    asyncio.run(stop_then_send())
    assert typed == ["Escape", "settled", "wipe", "wipe", "next", "Enter"]


@pytest.fixture
def launcher(tab, monkeypatch, tmp_path) -> SimpleNamespace:
    """A launcher's tab, where the first look for its claude is the slowest."""
    seen = SimpleNamespace(running=False, looks=0, typed=[], held=[], bodies=[])

    def look(_sid) -> bool:
        seen.looks += 1
        if seen.looks == 1:
            time.sleep(SLOW_SEC * 3)
        return seen.running

    def keys(_sid, text=None, key=None, enter=False):
        time.sleep(SLOW_SEC)
        seen.typed.append(key or text)
        return True

    async def body(_sid, text, key=None):
        seen.bodies.append(text)
        return {"ok": True}

    async def typeable(_sid, _timeout):
        return True

    monkeypatch.setattr(first_message, "uses_launcher", lambda _sid: True)
    monkeypatch.setattr(first_message, "claude_in_pane", look)
    monkeypatch.setattr(first_message, "tmux_send_keys", keys)
    monkeypatch.setattr(first_message, "ensure_pty_session_for", _nothing)
    monkeypatch.setattr(first_message, "register_claude_when_ready", _nothing)
    monkeypatch.setattr(first_message, "wait_until_typeable", typeable)
    monkeypatch.setattr(first_message, "resume_command_for", lambda _sid: None)
    monkeypatch.setattr(first_message, "first_message_command", lambda _sid, _file: "launch")
    monkeypatch.setattr(first_message, "_uploads_dir", lambda: tmp_path / "uploads")
    monkeypatch.setattr(first_message, "_placed_tier", lambda _sid, _text: "normal")
    monkeypatch.setattr(first_message, "_hold", lambda _sid, text, _send_id: seen.held.append(text))
    monkeypatch.setattr(routes, "_send_body", body)
    return seen


def _send_in_turn(*texts: str) -> None:
    async def send() -> None:
        await asyncio.gather(*(routes.pty_send(SID, {"text": text, "enter": True}, None) for text in texts))

    asyncio.run(send())


def test_messages_that_meet_a_slow_look_type_one_launch_and_keep_their_order(launcher):
    _send_in_turn("first", "second", "third")
    assert launcher.typed == ["C-u", "launch"]
    assert launcher.held == ["first", "second", "third"]


def test_messages_to_a_running_claude_keep_their_order_across_a_slow_look(launcher):
    launcher.running = True
    _send_in_turn("first", "second", "third")
    assert launcher.bodies == ["first", "second", "third"]


def test_two_messages_that_wake_one_shell_reopen_its_conversation_once(tab, monkeypatch):
    typed: list[str] = []

    def keys(_sid, text=None, key=None, enter=False):
        time.sleep(SLOW_SEC)
        typed.append(key or text)
        return True

    async def yes(*_args):
        return True

    import backend.sleep.sleeper as sleeper

    monkeypatch.setattr(sleeper, "wait_until_asleep", _nothing)
    monkeypatch.setattr(agent_messages, "claude_in_pane", lambda _sid: False)
    monkeypatch.setattr(agent_messages, "has_tmux_session", lambda _sid: True)
    monkeypatch.setattr(agent_messages, "uses_launcher", lambda _sid: False)
    monkeypatch.setattr(agent_messages, "resume_command_for", lambda _sid: "main --resume abc")
    monkeypatch.setattr(agent_messages, "ensure_pty_session_for", _nothing)
    monkeypatch.setattr(agent_messages, "register_claude_when_ready", _nothing)
    monkeypatch.setattr(agent_messages, "tmux_send_keys", keys)
    monkeypatch.setattr(agent_messages, "wait_for_claude_screen", yes)
    monkeypatch.setattr(agent_messages.input_ready, "wait_ready", yes)

    async def wake() -> None:
        await asyncio.gather(agent_messages._wake(SID), agent_messages._wake(SID))

    asyncio.run(wake())
    assert typed == ["C-u", "main --resume abc"]


def test_a_launch_is_being_decided_until_its_last_waiter_is_through():
    from backend.terminal import pane_order

    seen: list[tuple[bool, bool]] = []

    async def decide() -> None:
        async with pane_order.deciding_launch(SID) as waited:
            await asyncio.sleep(0)
        seen.append((waited, pane_order.is_deciding_launch(SID)))

    async def three() -> None:
        await asyncio.gather(decide(), decide(), decide())

    asyncio.run(three())
    assert seen == [(False, True), (True, True), (True, False)]
