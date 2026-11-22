"""A tab that closes while its terminal is being started leaves no terminal behind.

No tmux and no claude run: the look, the spawn and the stop are replaced.
"""
from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

import backend.routes.sessions as sessions
import backend.terminal.input_ready as input_ready
import backend.terminal.routes as routes
import backend.terminal.session_resolver as resolver
from backend._common import state
from backend._common.state import SessionDef
from backend.tests.async_run import run
from backend.terminal.runner import pty_sessions

SID = "ses_closing"
AGENT_ID = "agent_terminal"


class _Socket:
    """The socket of a terminal, and whether the tab's spawn lock was held while it was written to."""

    def __init__(self, session_id: str) -> None:
        self._session_id = session_id
        self.closed_with: int | None = None
        self.written_under_lock: list[bool] = []

    async def accept(self) -> None:
        return None

    async def send_text(self, _text: str) -> None:
        self.written_under_lock.append(resolver.spawn_lock(self._session_id).locked())

    async def close(self, code: int = 1000, reason: str = "") -> None:
        self.closed_with = code
        self.written_under_lock.append(resolver.spawn_lock(self._session_id).locked())


@pytest.fixture
def doors(monkeypatch, isolated_state) -> SimpleNamespace:
    seen = SimpleNamespace(spawned=[], stopped=[])
    isolated_state.sessions_meta[SID] = SessionDef(id=SID, agent_id="agent_a", title="closing", created_at=0)

    async def spawn(session_id, **_options):
        seen.spawned.append(session_id)
        await asyncio.sleep(0.05)
        return SimpleNamespace(exit_event=asyncio.Event())

    async def stop(session_id):
        seen.stopped.append((session_id, session_id in pty_sessions))
        return True

    for module in (routes, resolver):
        monkeypatch.setattr(module, "spawn_pty_session", spawn)
        monkeypatch.setattr(module, "has_tmux_session", lambda _sid: False)
    monkeypatch.setattr(routes, "_resolve_agent_cfg", lambda _sid: {})
    monkeypatch.setattr(routes, "_resolve_launch_alias", lambda _sid: None)
    monkeypatch.setattr(routes, "_resolve_autoresume_fallback", lambda _sid: None)
    monkeypatch.setattr(resolver, "resolve_agent_cfg", lambda _sid: {})
    monkeypatch.setattr(resolver, "resolve_extra_env", lambda *_args: {})
    monkeypatch.setattr(resolver, "resolve_launch_alias", lambda *_args, **_options: None)
    monkeypatch.setattr(resolver, "resolve_autoresume_fallback", lambda *_args, **_options: None)
    monkeypatch.setattr(resolver, "_wake_hook", None)
    monkeypatch.setattr(sessions, "stop_tab", stop)
    monkeypatch.setattr(sessions, "clear_child_folder", lambda _sid: None)
    monkeypatch.setattr(sessions.jsonl_watcher, "unregister", lambda _sid: None)
    monkeypatch.delenv("CPC_E2E", raising=False)
    resolver._spawn_locks.clear()
    yield seen
    pty_sessions.pop(SID, None)
    pty_sessions.pop(AGENT_ID, None)
    resolver._spawn_locks.clear()
    input_ready.forget(SID)


def test_a_close_during_a_start_waits_for_it_and_leaves_nothing(doors):
    async def scenario():
        starting = asyncio.create_task(resolver.ensure_pty_session_for(SID))
        while not doors.spawned:
            await asyncio.sleep(0.001)
        await sessions.delete_session(SID, "")
        await starting

    run(scenario())
    assert doors.stopped == [(SID, True)]      # stopped once the terminal being started was there to stop
    assert SID not in pty_sessions and SID not in state.sessions_meta


def test_a_start_that_waited_for_a_close_starts_nothing(doors, monkeypatch):
    looked: list[str] = []
    monkeypatch.setattr(resolver, "has_tmux_session", lambda sid: looked.append(sid) or False)

    async def scenario():
        async with resolver.spawn_lock(SID):
            starting = asyncio.create_task(resolver.ensure_pty_session_for(SID))
            await asyncio.sleep(0.01)
            del state.sessions_meta[SID]
        await starting

    run(scenario())
    assert doors.spawned == [] and looked == []


def test_a_terminal_opened_on_a_tab_that_closed_meanwhile_is_refused(doors, monkeypatch):
    monkeypatch.setattr(routes, "has_tmux_session", lambda sid: bool(state.sessions_meta.pop(sid, None)) and False)
    socket = _Socket(SID)
    run(routes.pty_socket(socket, SID))
    assert doors.spawned == []
    assert socket.closed_with == 4004 and not any(socket.written_under_lock)


def test_a_failed_start_is_told_outside_the_lock(doors, monkeypatch):
    async def fails(_session_id, **_options):
        raise RuntimeError("no pty")

    monkeypatch.setattr(routes, "spawn_pty_session", fails)
    socket = _Socket(SID)
    run(routes.pty_socket(socket, SID))
    assert socket.closed_with == 4002 and not any(socket.written_under_lock)


def test_the_terminal_of_an_agent_s_id_still_starts(doors, monkeypatch):
    monkeypatch.setitem(routes._config.AGENTS, AGENT_ID, {})

    async def stops_here(*_args):
        raise LookupError("the start is over")

    monkeypatch.setattr(routes, "send_connect_snapshot", stops_here)
    monkeypatch.setattr(routes, "_pump_from_client", lambda *_args: asyncio.sleep(0))
    with pytest.raises(LookupError):
        run(routes.pty_socket(_Socket(AGENT_ID), AGENT_ID))
    assert doors.spawned == [AGENT_ID]


def test_the_starting_mark_set_while_the_tab_stops_goes_with_it(doors, monkeypatch):
    async def stop(session_id):
        input_ready.mark_starting(session_id)
        return True

    monkeypatch.setattr(sessions, "stop_tab", stop)
    run(sessions.delete_session(SID, ""))
    assert input_ready.is_ready(SID) and not input_ready.launching(SID)
