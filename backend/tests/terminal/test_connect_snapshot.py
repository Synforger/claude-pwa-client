"""Tests for connect_snapshot: what a newly attached terminal is sent first, and when.

The capture itself is replaced; the real tmux is exercised in test_screen_capture_real_tmux.
"""
from __future__ import annotations

import asyncio
import json
import time

import pytest
from starlette.websockets import WebSocketState

import backend.terminal.connect_snapshot as cs
from backend.terminal.runner import PtySession
from backend.terminal.screen_snapshot import PaneScreen, build_snapshot

SID = "ses_snapshot"


class FakeWs:
    def __init__(self, state=WebSocketState.CONNECTED):
        self.client_state = state
        self.sent: list[tuple[str, object]] = []

    async def send_bytes(self, data: bytes) -> None:
        self.sent.append(("bytes", data))

    async def send_text(self, text: str) -> None:
        self.sent.append(("text", json.loads(text)))


def _screen(*, rows=3, cols=10, cursor=(1, 1)) -> PaneScreen:
    return PaneScreen(
        lines=tuple(f"row{n}" for n in range(rows)), cursor_x=cursor[0], cursor_y=cursor[1],
        is_cursor_visible=True, is_alternate=False, width=cols, height=rows,
    )


def _session() -> PtySession:
    return PtySession(
        session_id=SID, process=None, master_fd=-1,  # type: ignore[arg-type]
        output_queue=asyncio.Queue(maxsize=16), exit_event=asyncio.Event(),
    )


def _run_connect(ws, session, *, size=(3, 10), size_after=0.0, input_pump_done=False):
    """Runs send_connect_snapshot with a terminal that reports `size` after `size_after` seconds."""
    async def scenario():
        resized = asyncio.get_running_loop().create_future()
        pump = asyncio.create_task(asyncio.sleep(0 if input_pump_done else 30))
        if size is not None:
            asyncio.get_running_loop().call_later(size_after, resized.set_result, size)
        try:
            await cs.send_connect_snapshot(ws, session, resized, pump)
        finally:
            pump.cancel()
    asyncio.run(scenario())


@pytest.fixture(autouse=True)
def quick_waits(monkeypatch):
    monkeypatch.setattr(cs, "RESIZE_WAIT_SEC", 0.2)
    monkeypatch.setattr(cs, "SIZE_SETTLE_POLL_SEC", 0.0)
    monkeypatch.setattr(cs, "SIZE_SETTLE_ATTEMPTS", 4)


def test_the_screen_is_sent_as_the_first_binary_frame(monkeypatch):
    screen = _screen()
    monkeypatch.setattr(cs, "capture_pane_screen", lambda sid: screen)
    ws = FakeWs()
    _run_connect(ws, _session())
    assert ws.sent == [("bytes", build_snapshot(screen))]


def test_nothing_is_captured_before_the_terminal_has_sent_its_size(monkeypatch):
    captured_at: list[float] = []

    def capture(sid):
        captured_at.append(time.monotonic())
        return _screen()

    monkeypatch.setattr(cs, "capture_pane_screen", capture)
    started = time.monotonic()
    _run_connect(FakeWs(), _session(), size_after=0.1)
    assert len(captured_at) == 1
    assert captured_at[0] - started >= 0.09


def test_the_capture_is_retried_until_the_pane_has_the_size_the_terminal_asked_for(monkeypatch):
    answers = [_screen(rows=3, cols=80), _screen(rows=3, cols=80), _screen(rows=3, cols=10, cursor=(4, 2))]
    calls = []

    def capture(sid):
        calls.append(sid)
        return answers[len(calls) - 1]

    monkeypatch.setattr(cs, "capture_pane_screen", capture)
    ws = FakeWs()
    _run_connect(ws, _session(), size=(3, 10))
    assert len(calls) == 3
    assert ws.sent == [("bytes", build_snapshot(answers[2]))]


def test_a_pane_that_never_takes_the_size_is_captured_as_it_is(monkeypatch):
    stuck = _screen(rows=3, cols=80)
    calls = []
    monkeypatch.setattr(cs, "capture_pane_screen", lambda sid: calls.append(sid) or stuck)
    ws = FakeWs()
    _run_connect(ws, _session(), size=(3, 10))
    assert len(calls) == 4  # SIZE_SETTLE_ATTEMPTS
    assert ws.sent == [("bytes", build_snapshot(stuck))]


def test_a_terminal_that_sends_no_size_gets_a_capture_at_the_current_size(monkeypatch):
    screen = _screen(cols=80)
    calls = []
    monkeypatch.setattr(cs, "capture_pane_screen", lambda sid: calls.append(sid) or screen)
    ws = FakeWs()
    _run_connect(ws, _session(), size=None)
    assert len(calls) == 1
    assert ws.sent == [("bytes", build_snapshot(screen))]


def _queued(session) -> list[bytes]:
    return [session.output_queue.get_nowait() for _ in range(session.output_queue.qsize())]


def test_output_from_while_the_client_was_away_and_from_before_the_capture_is_dropped_but_later_output_is_kept(
    monkeypatch,
):
    session = _session()
    session.output_queue.put_nowait(b"while-away")

    def capture(sid):
        session.output_queue.put_nowait(b"during-capture")  # printed while tmux was being read
        return _screen()

    async def scenario():
        resized = asyncio.get_running_loop().create_future()
        pump = asyncio.create_task(asyncio.sleep(30))
        # printed after the client attached, before the capture began: the capture already shows it
        asyncio.get_running_loop().call_later(0.02, session.output_queue.put_nowait, b"before-capture")
        asyncio.get_running_loop().call_later(0.1, resized.set_result, (3, 10))
        await cs.send_connect_snapshot(FakeWs(), session, resized, pump)
        pump.cancel()

    monkeypatch.setattr(cs, "capture_pane_screen", capture)
    asyncio.run(scenario())
    assert _queued(session) == [b"during-capture"]


def test_drain_counts_what_it_drops():
    session = _session()
    for chunk in (b"a", b"b", b"c"):
        session.output_queue.put_nowait(chunk)
    assert cs.drain_output_queue(session) == 3
    assert cs.drain_output_queue(session) == 0


def test_drop_oldest_output_keeps_the_newer_chunks():
    session = _session()
    for chunk in (b"a", b"b", b"c"):
        session.output_queue.put_nowait(chunk)
    assert cs.drop_oldest_output(session, 2) == 2
    assert _queued(session) == [b"c"]
    assert cs.drop_oldest_output(session, 5) == 0


def test_a_screen_that_cannot_be_captured_is_reported_so_the_terminal_asks_for_a_repaint(monkeypatch):
    monkeypatch.setattr(cs, "capture_pane_screen", lambda sid: None)
    ws = FakeWs()
    _run_connect(ws, _session())
    assert ws.sent == [("text", {"type": "snapshot", "status": "none"})]


def test_without_a_screen_output_printed_after_the_client_attached_is_not_dropped(monkeypatch):
    monkeypatch.setattr(cs, "capture_pane_screen", lambda sid: None)
    session = _session()
    session.output_queue.put_nowait(b"while-away")

    async def scenario():
        resized = asyncio.get_running_loop().create_future()
        pump = asyncio.create_task(asyncio.sleep(30))
        asyncio.get_running_loop().call_later(0.02, session.output_queue.put_nowait, b"after-attach")
        asyncio.get_running_loop().call_later(0.1, resized.set_result, (3, 10))
        await cs.send_connect_snapshot(FakeWs(), session, resized, pump)
        pump.cancel()

    asyncio.run(scenario())
    assert _queued(session) == [b"after-attach"]


def test_an_unexpected_failure_of_the_capture_is_reported_the_same_way(monkeypatch):
    def broken(sid):
        raise ValueError("boom")

    monkeypatch.setattr(cs, "capture_pane_screen", broken)
    ws = FakeWs()
    _run_connect(ws, _session())
    assert ws.sent == [("text", {"type": "snapshot", "status": "none"})]


def test_a_client_that_left_is_sent_nothing(monkeypatch):
    monkeypatch.setattr(cs, "capture_pane_screen", lambda sid: _screen())
    ws = FakeWs(state=WebSocketState.DISCONNECTED)
    _run_connect(ws, _session(), size=None, input_pump_done=True)
    assert ws.sent == []


def test_a_client_that_leaves_while_the_screen_is_on_its_way_does_not_raise(monkeypatch):
    monkeypatch.setattr(cs, "capture_pane_screen", lambda sid: _screen())
    ws = FakeWs()

    async def gone(data):
        raise RuntimeError('Unexpected ASGI message "websocket.send"')

    ws.send_bytes = gone
    _run_connect(ws, _session())
