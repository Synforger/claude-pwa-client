"""`tabs ask --stream` prints each line of the backend's stream as it arrives (`backend/cli/ask.py`)."""
from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qsl

import pytest

from backend.cli import ask

REPO_ROOT = Path(__file__).resolve().parents[3]
TABS = REPO_ROOT / "backend" / "cli" / "tabs.py"
PARTIAL = {"type": "partial", "text": "The 港"}
FINAL = {"type": "final", "text": "The 港町 is quiet.", "session": "claude-uuid"}


class _StreamingBackend:
    """A backend that answers an ask with `lines` (or, for a `status` other than 200, with `body` as a plain HTTP error).
    It writes a line, then waits for the test to set the line's event in `released` before it writes the next one."""

    def __init__(self, lines: list[dict], *, status: int = 200, body: dict | None = None) -> None:
        self.asked: list[tuple[str, dict]] = []
        self.released = [threading.Event() for _ in lines]
        backend = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_POST(self):
                length = int(self.headers.get("Content-Length") or 0)
                backend.asked.append((self.path, dict(parse_qsl(self.rfile.read(length).decode()))))
                self.send_response(status)
                self.send_header("Content-Type", "application/json" if status != 200 else "application/x-ndjson")
                if status != 200:
                    raw = json.dumps(body or {}).encode()
                    self.send_header("Content-Length", str(len(raw)))
                    self.end_headers()
                    self.wfile.write(raw)
                    return
                self.send_header("Connection", "close")
                self.end_headers()
                for line, released in zip(lines, backend.released):
                    self.wfile.write((json.dumps(line, ensure_ascii=False) + "\n").encode("utf-8"))
                    self.wfile.flush()
                    released.wait(10)
                self.close_connection = True

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.server.server_port}"

    def close(self) -> None:
        for released in self.released:
            released.set()
        self.server.shutdown()
        self.server.server_close()


@pytest.fixture
def question(tmp_path) -> Path:
    file = tmp_path / "q.txt"
    file.write_text("Describe the tavern.", encoding="utf-8")
    return file


def _run(question: Path, backend: _StreamingBackend) -> int:
    for released in backend.released:                                   # these tests do not step the lines
        released.set()
    return ask.run(["Talemate の頭", str(question), "--stream", "--fresh"], lambda *a, **k: (0, {}), backend.url)


def test_every_line_goes_to_stdout_as_it_is_and_an_answer_at_the_end_is_success(question, capsys):
    backend = _StreamingBackend([PARTIAL, FINAL])
    try:
        assert _run(question, backend) == 0
    finally:
        backend.close()
    captured = capsys.readouterr()
    assert [json.loads(line) for line in captured.out.splitlines()] == [PARTIAL, FINAL] and "港" in captured.out
    assert captured.err == ""
    assert backend.asked == [("/sessions/Talemate%20%E3%81%AE%E9%A0%AD/ask",
                              {"text": "Describe the tavern.", "fresh": "true", "timeout_sec": "180.0", "stream": "true"})]


def test_a_failure_at_the_end_is_printed_as_its_line_and_on_stderr_and_fails(question, capsys):
    error = {"type": "error", "code": "ask_timeout", "message": "too long"}
    backend = _StreamingBackend([PARTIAL, error])
    try:
        assert _run(question, backend) == 1
    finally:
        backend.close()
    captured = capsys.readouterr()
    assert [json.loads(line) for line in captured.out.splitlines()] == [PARTIAL, error]
    assert "[ask_timeout]" in captured.err and "too long" in captured.err


def test_a_stream_that_ends_without_its_end_line_fails_as_unconfirmed(question, capsys):
    backend = _StreamingBackend([PARTIAL])
    try:
        assert _run(question, backend) == 1
    finally:
        backend.close()
    captured = capsys.readouterr()
    assert json.loads(captured.out) == PARTIAL and f"[{ask.UNCONFIRMED_CODE}]" in captured.err


def test_a_failure_before_the_typing_is_the_same_as_without_the_stream(question, capsys):
    detail = {"detail": {"code": "ask_tab_busy", "message": "busy"}}
    backend = _StreamingBackend([], status=409, body=detail)
    try:
        assert _run(question, backend) == 1
    finally:
        backend.close()
    captured = capsys.readouterr()
    assert captured.out == "" and "[ask_tab_busy]" in captured.err


def test_a_backend_that_is_not_there_asked_nothing(question, capsys):
    assert ask.run(["ses_head", str(question), "--stream"], lambda *a, **k: (0, {}), "http://127.0.0.1:1") == 1
    captured = capsys.readouterr()
    assert captured.out == "" and f"[{ask.NOT_SENT_CODE}]" in captured.err


def test_a_line_is_printed_before_the_next_one_comes(question):
    backend = _StreamingBackend([PARTIAL, FINAL])
    try:
        env = {"PATH": os.environ["PATH"], "HOME": str(question.parent), "PWA_PORT": str(backend.server.server_port),
               "PYTHONDONTWRITEBYTECODE": "1"}
        process = subprocess.Popen([sys.executable, str(TABS), "ask", "ses_head", str(question), "--stream"],
                                   stdout=subprocess.PIPE, text=True, env=env)
        try:
            assert json.loads(process.stdout.readline()) == PARTIAL    # read while the backend still holds the answer
            assert not backend.released[0].is_set() and process.poll() is None
            backend.released[0].set()
            assert json.loads(process.stdout.readline()) == FINAL
            backend.released[1].set()
            assert process.wait(timeout=20) == 0
        finally:
            process.kill()
            process.stdout.close()
    finally:
        backend.close()


def test_the_stream_asks_for_the_conversation_to_open_first(question):
    backend = _StreamingBackend([FINAL])
    try:
        for released in backend.released:
            released.set()
        saved = "7565f8b3-672d-46fe-8ad7-7f22afeae9d5"
        assert ask.run(["ses_head", str(question), "--stream", "--resume", saved, "--fork"],
                       lambda *a, **k: (0, {}), backend.url) == 0
    finally:
        backend.close()
    form = backend.asked[0][1]
    assert (form["stream"], form["resume"], form["fork"]) == ("true", saved, "true")
