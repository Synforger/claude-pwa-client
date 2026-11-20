"""`tabs ask` prints the answer of the asked tab, and runs outside every tab (`backend/cli/ask.py`)."""
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
SAVED = "7565f8b3-672d-46fe-8ad7-7f22afeae9d5"
BASE_URL = "http://127.0.0.1:1"                    # nothing listens: the tests of one answer never call it


@pytest.mark.parametrize(("argv", "expected"), [
    (["ses_head", "q.txt"], ask.AskArguments("ses_head", Path("q.txt"), False, 180.0)),
    (["ses_head", "q.txt", "--fresh"], ask.AskArguments("ses_head", Path("q.txt"), True, 180.0)),
    (["ses_head", "q.txt", "--timeout", "30", "--fresh"], ask.AskArguments("ses_head", Path("q.txt"), True, 30.0)),
    (["ses_head", "q.txt", "--stream"], ask.AskArguments("ses_head", Path("q.txt"), False, 180.0, True)),
    (["ses_head", "q.txt", "--stream", "--fresh"], ask.AskArguments("ses_head", Path("q.txt"), True, 180.0, True)),
    (["ses_head", "q.txt", "--stream", "--stream"], None),
    (["ses_head", "q.txt", "--json"], ask.AskArguments("ses_head", Path("q.txt"), False, 180.0, False, True)),
    (["ses_head", "q.txt", "--resume", SAVED], ask.AskArguments("ses_head", Path("q.txt"), False, 180.0, False, False, SAVED)),
    (["ses_head", "q.txt", "--fork", "--resume", SAVED, "--json"],
     ask.AskArguments("ses_head", Path("q.txt"), False, 180.0, False, True, SAVED, True)),
    (["ses_head", "q.txt", "--resume", SAVED, "--fresh"], None),
    (["ses_head", "q.txt", "--fork"], None),
    (["ses_head", "q.txt", "--resume"], None),
    (["ses_head", "q.txt", "--resume", "--fork"], None),
    (["ses_head", "q.txt", "--resume", SAVED, "--resume", SAVED], None),
    (["ses_head"], None),
    (["ses_head", "q.txt", "--fresh", "--fresh"], None),
    (["ses_head", "q.txt", "--timeout"], None),
    (["ses_head", "q.txt", "--timeout", "soon"], None),
    (["ses_head", "q.txt", "--timeout", "0"], None),
    (["ses_head", "q.txt", "--loud"], None),
])
def test_the_words_after_ask(argv, expected):
    assert ask.parse(argv) == expected


def test_the_answer_goes_to_stdout_and_the_call_waits_beyond_the_turn(tmp_path, capsys):
    question = tmp_path / "q.txt"
    question.write_text("Describe the tavern.", encoding="utf-8")
    calls = []

    def call(path, form, method=None, timeout=0.0):
        calls.append((path, form, timeout))
        return 200, {"ok": True, "id": "ses_head", "answer": "The tavern is quiet."}
    assert ask.run(["Talemate の頭", str(question), "--fresh", "--timeout", "60"], call, BASE_URL) == 0
    assert capsys.readouterr().out == "The tavern is quiet.\n"
    path, form, timeout = calls[0]
    assert path == "/sessions/Talemate%20%E3%81%AE%E9%A0%AD/ask"
    assert form == {"text": "Describe the tavern.", "fresh": "true", "timeout_sec": "60.0"}
    assert timeout == 60 + ask.WAKE_MARGIN_SEC


def test_json_prints_the_answer_with_its_conversation_and_resume_goes_to_the_backend(tmp_path, capsys):
    question = tmp_path / "q.txt"
    question.write_text("Where did we leave off?", encoding="utf-8")
    forms = []

    def call(path, form, method=None, timeout=0.0):
        forms.append(form)
        return 200, {"ok": True, "id": "ses_head", "answer": "At the 港", "session": "branch-uuid"}
    assert ask.run(["ses_head", str(question), "--json", "--resume", SAVED, "--fork"], call, BASE_URL) == 0
    assert json.loads(capsys.readouterr().out) == {"answer": "At the 港", "session": "branch-uuid"}
    assert forms[0]["resume"] == SAVED and forms[0]["fork"] == "true" and forms[0]["fresh"] == "false"
    assert ask.run(["ses_head", str(question), "--json"], call, BASE_URL) == 0
    assert "resume" not in forms[1]                              # no opening asked: the form is the old one


@pytest.mark.parametrize(("status", "body", "code"), [
    (504, {"detail": {"code": "ask_timeout", "message": "too long"}}, "ask_timeout"),
    (0, {"detail": {"message": "refused", "may_have_arrived": False}}, ask.NOT_SENT_CODE),
    (0, {"detail": {"message": "timed out", "may_have_arrived": True}}, ask.UNCONFIRMED_CODE),
    (500, {}, ask.UNCONFIRMED_CODE),
])
def test_a_failure_names_its_code_on_stderr(tmp_path, capsys, status, body, code):
    question = tmp_path / "q.txt"
    question.write_text("hello", encoding="utf-8")
    assert ask.run(["ses_head", str(question)], lambda *a, **k: (status, body), BASE_URL) == 1
    captured = capsys.readouterr()
    assert captured.out == "" and f"[{code}]" in captured.err


class _Backend:
    """A backend that answers every ask and remembers what it was asked."""

    def __init__(self) -> None:
        self.asked: list[tuple[str, dict]] = []
        backend = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_POST(self):
                length = int(self.headers.get("Content-Length") or 0)
                backend.asked.append((self.path, dict(parse_qsl(self.rfile.read(length).decode()))))
                body = json.dumps({"ok": True, "id": "ses_head", "answer": "line 1\nline 2"}).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def close(self) -> None:
        self.server.shutdown()
        self.server.server_close()


def test_a_program_outside_every_tab_runs_it(tmp_path):
    backend = _Backend()
    try:
        question = tmp_path / "q.txt"
        question.write_text("Describe the tavern.", encoding="utf-8")
        env = {"PATH": os.environ["PATH"], "HOME": str(tmp_path), "PWA_PORT": str(backend.server.server_port),
               "PYTHONDONTWRITEBYTECODE": "1"}                       # no PWA_SID, no agent folder
        done = subprocess.run([sys.executable, str(TABS), "ask", "ses_head", str(question)], capture_output=True,
                              text=True, timeout=60, env=env)
    finally:
        backend.close()
    assert done.returncode == 0, done.stderr
    assert done.stdout == "line 1\nline 2\n"
    assert backend.asked == [("/sessions/ses_head/ask", {"text": "Describe the tavern.", "fresh": "false",
                                                         "timeout_sec": "180.0"})]
