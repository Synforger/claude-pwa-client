"""`tabs ticket`: the words it takes, what it sends, what it prints, and a run of the real command against a stand-in backend."""
from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qsl, urlsplit

import pytest

from backend.cli import ticket

REPO_ROOT = Path(__file__).resolve().parents[3]
TABS = REPO_ROOT / "backend" / "cli" / "tabs.py"


@pytest.fixture
def tab(monkeypatch):
    monkeypatch.setenv("PWA_SID", "ses_a")


class _Calls:
    """A stand-in for the backend's call: what was called, and what it answers."""

    def __init__(self, status=200, body=None) -> None:
        self.status, self.body, self.made = status, body if body is not None else {"ok": True, "id": "home-261119-01", "status": "open"}, []

    def __call__(self, path, form=None, method=None, timeout=None):
        self.made.append((path, form, method, timeout))
        return self.status, self.body


def _file(tmp_path, name, text):
    path = tmp_path / name
    path.write_text(text, encoding="utf-8")
    return str(path)


def test_new_sends_the_title_and_the_text_and_prints_the_id(tab, tmp_path, capsys):
    calls = _Calls(body={"ok": True, "id": "home-261119-01", "place_outside": True, "operator_said": False})
    assert ticket.run(["new", "Move the title", _file(tmp_path, "b.txt", "Please.")], calls) == 0
    assert calls.made == [("/tickets", {"from": "ses_a", "title": "Move the title", "text": "Please."}, None, None)]
    assert capsys.readouterr().out == "home-261119-01 (操作者の発話なし)\n"


def test_new_with_the_operators_words_asks_for_them_and_says_when_they_did_not_go_in(tab, tmp_path, capsys):
    calls = _Calls(body={"ok": True, "id": "home-261119-01", "operator_said": False, "operator_said_left_out": "no_operator_words"})
    assert ticket.run(["new", "T", _file(tmp_path, "b.txt", "x"), "--operator-said"], calls) == 0
    assert calls.made[0][1]["operator_said"] == "true"
    assert "操作者の発話は入りませんでした" in capsys.readouterr().out


def test_add_and_close_send_their_files_and_the_close_file_is_optional(tab, tmp_path):
    calls = _Calls()
    assert ticket.run(["add", "home-261119-01", _file(tmp_path, "a.txt", "did it")], calls) == 0
    assert ticket.run(["close", "home-261119-01", _file(tmp_path, "c.txt", "all done")], calls) == 0
    assert ticket.run(["close", "home-261119-01"], calls) == 0
    assert [(path, form) for path, form, *_ in calls.made] == [
        ("/tickets/home-261119-01/entries", {"from": "ses_a", "text": "did it"}),
        ("/tickets/home-261119-01/close", {"from": "ses_a", "text": "all done"}),
        ("/tickets/home-261119-01/close", {"from": "ses_a"})]


@pytest.mark.parametrize("words", [["--kind", "decide", "{q}"], ["{q}", "--kind", "decide"]])
def test_ask_takes_its_kind_before_or_after_the_file(tab, tmp_path, words):
    calls = _Calls()
    question = _file(tmp_path, "q.txt", "A or B?")
    assert ticket.run(["ask", "home-261119-01", *[question if w == "{q}" else w for w in words]], calls) == 0
    assert calls.made[0][:2] == ("/tickets/home-261119-01/asks", {"from": "ses_a", "kind": "decide", "text": "A or B?"})


def test_ask_sends_the_recommendation_from_its_file(tab, tmp_path):
    calls = _Calls()
    words = ["ask", "home-261119-01", "--kind", "mac", _file(tmp_path, "q.txt", "plug it in"), "--recommend",
             _file(tmp_path, "r.txt", "now")]
    assert ticket.run(words, calls) == 0
    assert calls.made[0][1] == {"from": "ses_a", "kind": "mac", "text": "plug it in", "recommend": "now"}


def test_pass_waits_as_long_as_a_message_that_wakes_a_tab_and_prints_who_has_it(tab, capsys):
    calls = _Calls(body={"ok": True, "id": "home-261119-01", "to": "ses_b"})
    assert ticket.run(["pass", "home-261119-01", "client work"], calls) == 0
    assert calls.made == [("/tickets/home-261119-01/pass", {"from": "ses_a", "to": "client work"}, None, ticket.LONG_TIMEOUT_SEC)]
    assert capsys.readouterr().out == "渡しました: home-261119-01 → ses_b\n"


def test_a_ticket_of_the_other_machine_is_used_with_the_same_commands_to_this_machines_backend(tab, tmp_path, capsys):
    calls = _Calls(body={"ok": True, "id": "company-261119-03", "status": "open", "to": "company:ses_x"})
    note = _file(tmp_path, "n.txt", "did it")
    assert ticket.run(["add", "company-261119-03", note], calls) == 0
    assert ticket.run(["close", "company-261119-03", note], calls) == 0
    assert ticket.run(["pass", "company-261119-03", "company:notes"], calls) == 0
    assert [(path, timeout) for path, _form, _method, timeout in calls.made] == [
        ("/tickets/company-261119-03/entries", ticket.LONG_TIMEOUT_SEC), ("/tickets/company-261119-03/close", ticket.LONG_TIMEOUT_SEC),
        ("/tickets/company-261119-03/pass", ticket.LONG_TIMEOUT_SEC)]
    assert calls.made[2][1] == {"from": "ses_a", "to": "company:notes"}
    assert "渡しました: company-261119-03 → company:ses_x" in capsys.readouterr().out


def test_show_of_a_ticket_of_the_other_machine_says_whose_it_is(tab, capsys):
    body = {"ok": True, "id": "company-261119-03", "status": "open", "home": "company", "holder": "company:ses_x", "entries": []}
    assert ticket.run(["show", "company-261119-03"], _Calls(body=body)) == 0
    assert capsys.readouterr().out.splitlines()[0] == "票 company-261119-03 (open) (company の機械の票) 持ち主: company:ses_x"


@pytest.mark.parametrize("word, code", [("ask", "ticket_ask_elsewhere"), ("add", "ticket_peer_down"), ("pass", "ticket_inside_boundary")])
def test_what_the_other_machines_ticket_refuses_is_printed_with_its_code(tab, tmp_path, capsys, word, code):
    refused = _Calls(status=409, body={"detail": {"code": code, "message": "the reason"}})
    words = {"ask": ["ask", "company-261119-03", "--kind", "decide", _file(tmp_path, "q.txt", "x")],
             "add": ["add", "company-261119-03", _file(tmp_path, "a.txt", "x")], "pass": ["pass", "company-261119-03", "ses_b"]}[word]
    assert ticket.run(words, refused) == 1
    assert f"[{code}]: the reason" in capsys.readouterr().err


def test_pass_says_when_the_line_is_kept_for_a_stopped_tab(tab, capsys):
    ticket.run(["pass", "home-261119-01", "ses_b"], _Calls(body={"ok": True, "id": "x", "to": "ses_b", "kept": True}))
    assert "口座の線で止まっています" in capsys.readouterr().out


def test_show_reads_with_the_tab_as_the_reader_and_prints_every_line(tab, capsys):
    body = {"ok": True, "id": "home-261119-01", "status": "waiting-operator", "wants": "decide", "holder": "ses_a", "entries": [
        {"kind": "opened", "at": "t1", "tab_title": "client work", "tier": "projects/AP", "title": "Title", "text": "Request"},
        {"kind": "operator", "at": "t1", "tab_title": "client work", "tier": "projects/AP", "text": "please"},
        {"kind": "added", "at": "t2", "hidden": True, "text": "読めない境界の書き足し"},
        {"kind": "asked", "at": "t3", "tab_title": "notes", "tier": "", "ask_kind": "decide", "text": "A or B?", "recommend": "A"},
        {"kind": "passed", "at": "t4", "tab_title": "notes", "tier": "", "to": "ses_c", "text": ""}]}
    calls = _Calls(body=body)
    assert ticket.run(["show", "home-261119-01"], calls) == 0
    assert calls.made == [("/tickets/home-261119-01?reader=ses_a", None, "GET", None)]
    out = capsys.readouterr().out
    assert out.startswith("票 home-261119-01 (waiting-operator / 求める物: decide) 持ち主: ses_a")
    assert "--- t1 opened client work (projects/AP) 「Title」\nRequest" in out
    assert "--- t1 operator 操作者\nplease" in out
    assert "--- t2 読めない境界の書き足し" in out
    assert "--- t3 asked [decide] notes (-)\nA or B?\n\n推奨: A" in out
    assert "--- t4 passed → ses_c notes (-)" in out


@pytest.mark.parametrize("words", [
    [], ["unknown"], ["new"], ["new", "T"], ["new", "T", "b", "--loud"], ["show"], ["show", "a", "b"], ["add", "id"],
    ["ask", "id", "f"], ["ask", "id", "--kind", "later", "f"], ["ask", "id", "--kind", "decide"],
    ["ask", "id", "--kind", "decide", "f", "g"], ["ask", "id", "--kind", "decide", "--kind", "mac", "f"],
    ["close"], ["close", "id", "f", "g"], ["pass", "id"],
])
def test_words_that_are_not_a_form_print_the_usage_and_call_nothing(tab, capsys, words):
    calls = _Calls()
    assert ticket.run(words, calls) == 2
    assert calls.made == [] and "tabs ticket new" in capsys.readouterr().err


def test_without_a_tab_id_nothing_is_called(monkeypatch, capsys):
    monkeypatch.delenv("PWA_SID", raising=False)
    calls = _Calls()
    assert ticket.run(["show", "home-261119-01"], calls) == 1
    assert calls.made == [] and "PWA_SID" in capsys.readouterr().err


def test_a_file_that_cannot_be_read_is_said_and_nothing_is_called(tab, tmp_path, capsys):
    calls = _Calls()
    assert ticket.run(["add", "home-261119-01", str(tmp_path / "missing.txt")], calls) == 1
    assert calls.made == [] and "missing.txt を読めません" in capsys.readouterr().err


@pytest.mark.parametrize(("word", "heading"), [
    (["new", "T", "{f}"], "票を開けませんでした"), (["show", "id"], "票を読めませんでした"),
    (["add", "id", "{f}"], "票に書き足せませんでした"), (["ask", "id", "--kind", "mac", "{f}"], "票を操作者の前に出せませんでした"),
    (["close", "id"], "票を閉じられませんでした"), (["pass", "id", "ses_b"], "票を渡せませんでした"),
])
def test_a_failure_goes_to_stderr_with_the_heading_and_the_code_and_ends_with_1(tab, tmp_path, capsys, word, heading):
    body = {"detail": {"code": "ticket_closed", "message": "その票は閉じています"}}
    words = [str(_file(tmp_path, "f.txt", "x")) if w == "{f}" else w for w in word]
    assert ticket.run(words, _Calls(status=409, body=body)) == 1
    captured = capsys.readouterr()
    assert captured.out == "" and captured.err == f"tabs: {heading} [ticket_closed]: その票は閉じています\n"


@pytest.mark.parametrize(("status", "body", "code"), [
    (0, {"detail": {"message": "refused", "may_have_arrived": False}}, ticket.NOT_SENT_CODE),
    (0, {"detail": {"message": "timed out", "may_have_arrived": True}}, ticket.UNCONFIRMED_CODE),
    (500, {}, ticket.UNCONFIRMED_CODE),
])
def test_an_answer_with_no_code_gets_one_that_says_whether_the_line_may_be_in_the_ticket(tab, capsys, status, body, code):
    assert ticket.run(["show", "id"], _Calls(status=status, body=body)) == 1
    assert f"[{code}]" in capsys.readouterr().err


class _Backend:
    """A stand-in backend that answers `{"ok": true, ...}` and remembers each call."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, str, dict]] = []
        backend = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def _answer(self, form):
                backend.calls.append((self.command, self.path, form))
                body = json.dumps({"ok": True, "id": "home-261119-01", "status": "open", "entries": []}).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def do_POST(self):
                length = int(self.headers.get("Content-Length") or 0)
                self._answer(dict(parse_qsl(self.rfile.read(length).decode())))

            def do_GET(self):
                self._answer(dict(parse_qsl(urlsplit(self.path).query)))

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def close(self) -> None:
        self.server.shutdown()
        self.server.server_close()


def test_the_real_command_reaches_the_backend_through_tabs(tmp_path):
    backend = _Backend()
    try:
        env = {"PATH": os.environ["PATH"], "HOME": str(tmp_path), "PWA_PORT": str(backend.server.server_port),
               "PWA_SID": "ses_a", "PYTHONDONTWRITEBYTECODE": "1"}
        body = _file(tmp_path, "body.txt", "Please move it.")
        opened = subprocess.run([sys.executable, str(TABS), "ticket", "new", "Move it", body], capture_output=True, text=True,
                                timeout=60, env=env)
        shown = subprocess.run([sys.executable, str(TABS), "ticket", "show", "home-261119-01"], capture_output=True, text=True,
                               timeout=60, env=env)
        misused = subprocess.run([sys.executable, str(TABS), "ticket", "show"], capture_output=True, text=True, timeout=60, env=env)
    finally:
        backend.close()
    assert opened.returncode == 0, opened.stderr
    assert shown.returncode == 0, shown.stderr
    assert misused.returncode == 2 and "tabs ticket new" in misused.stderr
    assert backend.calls == [("POST", "/tickets", {"from": "ses_a", "title": "Move it", "text": "Please move it."}),
                             ("GET", "/tickets/home-261119-01?reader=ses_a", {"reader": "ses_a"})]
