"""Tests for a launch that is slow to start: one launch at a time per tab, and the messages that arrive meanwhile.

On a loaded machine a new pane's shell can take minutes to show its prompt. The waits for a launch end long before
that, and nothing may then type a second launch into the pane, or type a message into a claude that has not announced
itself (= the message is lost in its start).
"""
from __future__ import annotations

import asyncio

import pytest

import backend.terminal.first_message as fm
import backend.terminal.receipt as receipt
import backend.terminal.routes as routes
from backend.terminal import input_ready

SID = "ses_slow"


def _run(coro):
    return asyncio.run(coro)


@pytest.fixture(autouse=True)
def clean_state():
    input_ready.forget(SID)
    fm._held.pop(SID, None)
    yield
    input_ready.forget(SID)
    fm._held.pop(SID, None)
    fm._typers.pop(SID, None)


def _timeout_without_announcement() -> None:
    """What the end of a wait does to the flag: it is raised although no claude announced itself."""
    input_ready._slot(SID).set()


# --- input_ready: the launch in flight -------------------------------------------------------------------------------

def test_a_launch_is_in_flight_until_its_claude_announces_itself():
    input_ready.mark_starting(SID)
    assert input_ready.launching(SID)
    _timeout_without_announcement()
    assert input_ready.is_ready(SID)
    assert input_ready.launching(SID)  # the end of a wait does not end the launch
    input_ready.mark_ready(SID)
    assert not input_ready.launching(SID)


def test_a_launch_is_given_up_after_the_limit(monkeypatch):
    monkeypatch.setattr(input_ready, "LAUNCH_GIVE_UP_SEC", 0.02)
    monkeypatch.setattr(input_ready, "LAUNCH_LOOK_SEC", 0.005)
    input_ready.mark_starting(SID)
    assert _run(input_ready.wait_launched(SID)) is False
    assert not input_ready.launching(SID)


def test_waiting_for_a_launch_ends_when_its_claude_announces_itself(monkeypatch):
    monkeypatch.setattr(input_ready, "LAUNCH_LOOK_SEC", 0.005)
    input_ready.mark_starting(SID)

    async def scenario():
        waiting = asyncio.create_task(input_ready.wait_launched(SID))
        await asyncio.sleep(0.02)
        assert not waiting.done()
        input_ready.mark_ready(SID)
        return await waiting
    assert _run(scenario()) is True


def test_with_no_launch_in_flight_nothing_is_waited_for():
    assert not input_ready.launching(SID)
    assert _run(input_ready.wait_launched(SID)) is True


# --- the send routes hold what arrives during a launch ---------------------------------------------------------------

@pytest.fixture
def pane(monkeypatch):
    """A tab whose launch was typed and has not started yet. → (keys typed into the pane, messages delivered)."""
    keys: list[str] = []
    delivered: list[str] = []

    def fake_keys(_sid, text=None, key=None, enter=False):
        keys.append(text or key)
        return True

    async def fake_deliver(_sid, text):
        delivered.append(text)
        return True

    async def screen_up(_sid):
        return True

    async def nothing(*_a, **_k):
        return None

    monkeypatch.setattr(routes, "_require_session", lambda _sid: None)
    monkeypatch.setattr(fm, "tmux_send_keys", fake_keys)
    monkeypatch.setattr(fm, "uses_launcher", lambda _sid: True)
    monkeypatch.setattr(fm, "claude_in_pane", lambda _sid: False)
    monkeypatch.setattr(fm, "ensure_pty_session_for", nothing)

    async def typeable(_sid, _timeout):
        return True
    monkeypatch.setattr(fm, "wait_until_typeable", typeable)
    monkeypatch.setattr(fm, "register_claude_when_ready", nothing)
    monkeypatch.setattr(fm, "resume_command_for", lambda _sid: "agent_a --resume claude-a")
    monkeypatch.setattr(receipt, "deliver_to_woken", fake_deliver)
    monkeypatch.setattr(receipt, "wait_for_claude_screen", screen_up)
    monkeypatch.setattr(input_ready, "LAUNCH_LOOK_SEC", 0.005)
    return keys, delivered


def test_messages_sent_during_a_slow_launch_are_held_and_typed_in_order_once_claude_is_up(pane):
    # Intent: the operator writes to a tab woken from sleep while its shell is still starting. Nothing is typed into
    # the pane (= no second launch, no message into a claude that is not listening), and every message arrives.
    keys, delivered = pane
    input_ready.mark_starting(SID)  # the spawn typed the reopening command

    async def scenario():
        first = await routes.pty_send(SID, {"text": "hello", "enter": True}, None)
        _timeout_without_announcement()  # the send route's own wait ended meanwhile
        second = await routes.pty_send(SID, {"text": "are you there", "enter": True}, None)
        await asyncio.sleep(0.02)
        assert delivered == []
        input_ready.mark_ready(SID)  # SessionStart
        await asyncio.gather(*fm._typers.values())
        return first, second

    first, second = _run(scenario())
    assert first == second == {"ok": True, "launched": True}
    assert keys == []
    assert delivered == ["hello", "are you there"]


def test_a_reopened_tab_types_its_message_only_after_its_claude_announces_itself(pane):
    keys, delivered = pane

    class _Sleeping:
        child = False
        tier_tab = None
        tier = None
        parent_id = None

        def sleeping_claude_sid(self):
            return "claude-a"

    fm.sessions_meta[SID] = _Sleeping()
    try:
        async def scenario():
            out = await fm.launch_with_first_message(SID, "hello")
            await asyncio.sleep(0.02)
            assert delivered == []  # no blind typing after a fixed wait
            # a second message meanwhile: held, the reopening is not typed again
            assert await routes.pty_send(SID, {"text": "again", "enter": True}, None) == {"ok": True, "launched": True}
            input_ready.mark_ready(SID)
            await asyncio.gather(*fm._typers.values())
            return out
        assert _run(scenario()) == {"ok": True, "launched": True}
    finally:
        fm.sessions_meta.pop(SID, None)
    assert keys == ["C-u", "agent_a --resume claude-a"]
    assert delivered == ["hello", "again"]


def test_a_launch_given_up_sends_its_held_messages_again(pane, monkeypatch):
    _, delivered = pane
    resent: list[str] = []

    async def fake_send(_sid, payload, _key=None):
        resent.append(payload["text"])
        return {"ok": True}
    monkeypatch.setattr(routes, "pty_send", fake_send)
    input_ready.mark_starting(SID)

    async def scenario():
        assert fm.hold_while_launching(SID, "one") is not None
        assert fm.hold_while_launching(SID, "two") is not None
        # the limit passes only once both are held, however slow the machine is
        monkeypatch.setattr(input_ready, "LAUNCH_GIVE_UP_SEC", 0.0)
        await asyncio.gather(*fm._typers.values())
    _run(scenario())
    assert resent == ["one", "two"]
    assert delivered == []
    # the abandoned launch holds nothing back: the resent messages may launch again
    assert input_ready.is_ready(SID) and not input_ready.launching(SID)


def test_with_no_launch_in_flight_the_send_is_not_held():
    assert fm.hold_while_launching(SID, "hello") is None
    assert SID not in fm._held


# --- the autoresume watchdog counts from the shell's prompt ----------------------------------------------------------

def test_the_autoresume_watchdog_waits_for_the_shell_before_it_looks_for_claude(monkeypatch):
    import backend.jsonl.jsonl_watcher as jsonl_watcher  # noqa: PLC0415
    import backend.terminal.pty_discover as pd  # noqa: PLC0415
    import backend.terminal.runner as runner  # noqa: PLC0415
    typed: list[str] = []
    monkeypatch.setattr(runner, "tmux_send_keys", lambda _sid, text=None, enter=False: typed.append(text) or True)
    monkeypatch.setattr(pd, "tmux_pane_pids", lambda _sid: [])
    monkeypatch.setattr(jsonl_watcher, "list_bindings", lambda: {})

    class _Session:
        control_mode = True
        prompt_ready = asyncio.Event()

    async def scenario():
        _Session.prompt_ready = asyncio.Event()
        watchdog = asyncio.create_task(runner._autoresume_watchdog(
            SID, "fallback", initial_delay=0, max_wait=0.01, interval=0.005, session=_Session()))
        await asyncio.sleep(0.05)
        assert typed == []  # the shell has not run the launch yet
        _Session.prompt_ready.set()
        await watchdog
    _run(scenario())
    assert typed == ["fallback"]
