"""Whether an engine takes connections, read from a real socket (`backend/engine_wake/engine_service.py`)."""
from __future__ import annotations

import socket

from backend.engine_wake import engine_service


def test_a_listening_engine_answers_and_a_closed_port_does_not():
    with socket.socket() as server:
        server.bind(("127.0.0.1", 0))
        server.listen()
        port = server.getsockname()[1]
        assert engine_service.answers(f"http://127.0.0.1:{port}")
    assert not engine_service.answers(f"http://127.0.0.1:{port}")


def test_launchctl_refusing_says_why(monkeypatch):
    monkeypatch.setattr(engine_service.os, "getuid", lambda: 501)
    assert engine_service.start("no.such.service.for.this.test")
