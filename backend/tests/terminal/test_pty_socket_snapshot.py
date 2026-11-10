"""What `/ws/pty/{sid}` sends first: the pane's current screen, ahead of live output.

The route runs for real (a TestClient websocket); the tmux read is replaced, and the pane is a PtySession
without a process. See test_screen_capture_real_tmux for the real tmux.
"""
from __future__ import annotations

import asyncio
import json

import pytest
from fastapi import FastAPI
from starlette.testclient import TestClient

import backend.terminal.connect_snapshot as cs
import backend.terminal.routes as routes
from backend.terminal.runner import PtySession, pty_sessions
from backend.terminal.screen_snapshot import PaneScreen, build_snapshot

SID = "ses_socket_snapshot"
SCREEN = PaneScreen(
    lines=("hello", "world"), cursor_x=5, cursor_y=0, is_cursor_visible=True, is_alternate=False,
    width=20, height=2,
)


@pytest.fixture
def pane(monkeypatch):
    """A live pane with output waiting in its queue from before the client attached."""
    session = PtySession(
        session_id=SID, process=None, master_fd=-1,  # type: ignore[arg-type]
        output_queue=asyncio.Queue(maxsize=16), exit_event=asyncio.Event(),
    )
    session.output_queue.put_nowait(b"backlog-while-away")
    monkeypatch.setitem(routes.sessions_meta, SID, {})
    monkeypatch.setitem(pty_sessions, SID, session)
    monkeypatch.setattr(cs, "RESIZE_WAIT_SEC", 0.3)
    monkeypatch.setattr(cs, "SIZE_SETTLE_POLL_SEC", 0.0)
    return session


@pytest.fixture
def client():
    app = FastAPI()
    app.include_router(routes.router)
    with TestClient(app) as test_client:
        yield test_client


def test_the_first_frame_is_the_screen_then_live_output_and_the_backlog_is_dropped(pane, client, monkeypatch):
    def capture(session_id):
        pane.output_queue.put_nowait(b"live-after-capture")  # printed while tmux was being read: kept
        return SCREEN

    monkeypatch.setattr(cs, "capture_pane_screen", capture)
    with client.websocket_connect(f"/ws/pty/{SID}") as ws:
        ws.send_text(json.dumps({"type": "resize", "rows": 2, "cols": 20}))
        assert ws.receive_bytes() == build_snapshot(SCREEN)
        assert ws.receive_bytes() == b"live-after-capture"


def test_the_screen_is_captured_only_after_the_terminal_has_sent_its_size(pane, client, monkeypatch):
    calls = []
    monkeypatch.setattr(cs, "capture_pane_screen", lambda sid: calls.append(sid) or SCREEN)
    with client.websocket_connect(f"/ws/pty/{SID}") as ws:
        assert calls == []
        ws.send_text(json.dumps({"type": "resize", "rows": 2, "cols": 20}))
        ws.receive_bytes()
        assert calls == [SID]


def test_a_terminal_that_sends_no_size_still_gets_the_screen(pane, client, monkeypatch):
    monkeypatch.setattr(cs, "capture_pane_screen", lambda sid: SCREEN)
    with client.websocket_connect(f"/ws/pty/{SID}") as ws:
        assert ws.receive_bytes() == build_snapshot(SCREEN)


def test_without_a_screen_the_terminal_is_told_and_live_output_follows(pane, client, monkeypatch):
    monkeypatch.setattr(cs, "capture_pane_screen", lambda sid: None)
    with client.websocket_connect(f"/ws/pty/{SID}") as ws:
        ws.send_text(json.dumps({"type": "resize", "rows": 2, "cols": 20}))
        assert json.loads(ws.receive_text()) == {"type": "snapshot", "status": "none"}
        client.portal.call(pane.output_queue.put, b"live")  # from the server's own loop thread
        assert ws.receive_bytes() == b"live"
