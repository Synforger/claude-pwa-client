"""`tabs` (= backend/cli/tabs.py) の確認: エージェントの folder の決め方、 子のタブの口、 起動し直しの口、 一覧の伏せ方。

作り物の HOME・エージェントの folder (= 階層の決め方だけを持つ作り物の起動 script 付き)・backend (= 呼ばれた口と中身を
記録し、 決めた答えを返す) を立てて、 別 process で打つ。
"""
import importlib.util
import json
import os
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qsl

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
TABS = REPO_ROOT / "backend" / "cli" / "tabs.py"
SHIM = REPO_ROOT / "bin" / "tabs"
SESSION = "11111111-2222-3333-4444-555555555555"

# エージェントの起動 script のうち tabs が使う 4 つ (= 階層の決め方) だけを持つ作り物
LAUNCHER = '''
import json
import os
import re
from pathlib import Path

AGENT = Path(os.environ.get("ARK_ROOT", Path(__file__).resolve().parents[2]))
CHILD_START = re.compile(r"<child-start>\\ntier=(.*?)\\n</child-start>", re.S)


def tier_folder(tier):
    if tier == "normal":
        return AGENT
    folder = AGENT / tier
    return folder if tier.startswith("projects/") and folder.is_dir() else None


def tier_of(message):
    found = CHILD_START.search(message)
    tier = found.group(1) if found else "normal"
    return tier, tier_folder(tier) or AGENT


def first_message(config_dir, session):
    for path in config_dir.glob(f"projects/*/{session}.jsonl"):
        for line in path.read_text(encoding="utf-8").splitlines():
            record = json.loads(line)
            if record.get("type") == "user":
                return record["message"]["content"]
    return ""
'''


class Backend:
    """作り物の backend。 口ごとの答え (= status) は `answers`、 タブの一覧は `tabs`、 呼ばれた口は `calls`。"""

    def __init__(self):
        self.calls: list[dict] = []
        self.answers: dict[str, int] = {}
        self.tabs: list[dict] = []
        backend = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def reply(self, status: int, body: object) -> None:
                data = json.dumps(body).encode()
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def handle_any(self, method: str) -> None:
                length = int(self.headers.get("Content-Length") or 0)
                form = dict(parse_qsl(self.rfile.read(length).decode())) if length else {}
                backend.calls.append({"method": method, "path": self.path, "form": form})
                if method == "GET" and self.path == "/sessions":
                    return self.reply(200, backend.tabs)
                if method == "POST" and self.path.endswith("/children"):
                    if backend.answers.get("children", 200) != 200:
                        return self.reply(backend.answers["children"], {"detail": {"code": "child_session_limit", "message": "full"}})
                    return self.reply(200, {"id": "ses_new", "child": True, "parent_id": "ses_parent", "started": True})
                if method == "POST" and self.path == "/agent-messages":
                    if backend.answers.get("send", 200) != 200:
                        return self.reply(backend.answers["send"], {"detail": {"code": "agent_message_refused", "message": "no"}})
                    return self.reply(200, {"ok": True, "to": form.get("to")})
                if method == "DELETE":
                    return self.reply(200, {"ok": True})
                return self.reply(404, {})

            def do_GET(self):
                self.handle_any("GET")

            def do_POST(self):
                self.handle_any("POST")

            def do_DELETE(self):
                self.handle_any("DELETE")

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.port = self.server.server_port
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def close(self) -> None:
        self.server.shutdown()
        self.server.server_close()

    def called(self, method: str, path: str) -> list[dict]:
        return [c for c in self.calls if c["method"] == method and c["path"] == path]


class Tabs:
    """作り物の HOME とエージェントの folder と backend に向けて `tabs` を打つ。"""

    def __init__(self, work: Path, backend: Backend):
        self.work, self.backend = work, backend
        self.home, self.agent = work / "home", work / "agent"
        (self.home / ".claude/projects/-agent").mkdir(parents=True)
        (self.agent / ".tooling/lib").mkdir(parents=True)
        (self.agent / "notes").mkdir()
        (self.agent / ".tooling/lib/claude-launch.py").write_text(LAUNCHER, encoding="utf-8")
        self.record = self.home / f".claude/projects/-agent/{SESSION}.jsonl"
        self.out = self.err = ""

    def env(self, **extra: str) -> dict[str, str]:
        base = {"PATH": os.environ["PATH"], "HOME": str(self.home), "ARK_ROOT": str(self.agent), "PWA_SID": "ses_parent",
                "PWA_PORT": str(self.backend.port), "ARK_TIER": "normal", "CLAUDE_CODE_SESSION_ID": SESSION,
                "PYTHONDONTWRITEBYTECODE": "1"}
        return {**base, **extra}

    def run(self, *args: str, **extra: str) -> int:
        """`tabs` を打つ。 呼ばれた口の記録は打つごとに空にする。 値が空の `extra` はその環境変数を外す。"""
        self.backend.calls.clear()
        env = {k: v for k, v in self.env(**extra).items() if v != ""}
        done = subprocess.run([sys.executable, str(TABS), *args], capture_output=True, text=True, timeout=60, env=env)
        self.out, self.err = done.stdout, done.stderr
        return done.returncode

    def note(self, name: str, text: str) -> Path:
        path = self.agent / "notes" / f"{name}.md"
        path.write_text(text, encoding="utf-8")
        return path

    def used(self, tool: str, path: Path) -> None:
        """会話の記録に、 その道具がその path を扱った行を足す。"""
        row = {"type": "assistant", "message": {"content": [{"type": "tool_use", "name": tool, "input": {"file_path": str(path)}}]}}
        with self.record.open("a", encoding="utf-8") as f:
            f.write(json.dumps(row) + "\n")


@pytest.fixture
def backend():
    server = Backend()
    yield server
    server.close()


@pytest.fixture
def tabs(tmp_path, backend):
    return Tabs(tmp_path.resolve(), backend)


# --- エージェントの folder の場所 -------------------------------------------------------

def where(env: dict[str, str], *argv: str) -> subprocess.CompletedProcess:
    """新しい process で、 tabs が決めたエージェントの folder と印の置き場を JSON で出させる (= 器の根と HOME は import の時に読まれる)。"""
    script = ("import json, sys; from backend.cli import tabs; tabs.main(sys.argv[1:]); "
              "print(json.dumps({'agent': str(tabs.agent_dir()), 'marks': str(tabs.MARKS)}))")
    return subprocess.run([sys.executable, "-c", script, *argv], cwd=REPO_ROOT, capture_output=True, text=True, timeout=60,
                          env={"PATH": os.environ["PATH"], "PYTHONPATH": str(REPO_ROOT), "PYTHONDONTWRITEBYTECODE": "1", **env})


def placed(done: subprocess.CompletedProcess) -> dict[str, str]:
    assert done.returncode == 0, done.stderr
    return json.loads(done.stdout.strip().splitlines()[-1])


def add_launcher(root: Path, name: str) -> Path:
    """器の根の `agents/<name>/` に、 起動 script を持つエージェントの folder を作る。"""
    folder = root / "agents" / name
    (folder / ".tooling/lib").mkdir(parents=True)
    (folder / ".tooling/lib/claude-launch.py").write_text(LAUNCHER, encoding="utf-8")
    return folder


def test_without_a_root_the_marks_keep_their_old_place_and_the_agent_must_be_named(tmp_path):
    done = where({"HOME": str(tmp_path)})
    assert done.returncode == 1 and "エージェントの folder が分かりません" in done.stderr
    done = where({"HOME": str(tmp_path)}, "--agent-dir", str(tmp_path / "agent"), "nothing")
    assert placed(done) == {"agent": str(tmp_path / "agent"), "marks": str(tmp_path / ".cache/area-guard")}


def test_a_root_gives_the_only_agent_and_the_marks_place(tmp_path):
    root = tmp_path / "platform"
    agent = add_launcher(root, "main")
    done = where({"HOME": str(tmp_path), "AGENT_PLATFORM_ROOT": str(root)})
    assert placed(done) == {"agent": str(agent), "marks": str(root / "state/guard/marks")}


def test_a_root_with_several_agents_asks_for_one(tmp_path):
    root = tmp_path / "platform"
    add_launcher(root, "one")
    add_launcher(root, "two")
    done = where({"HOME": str(tmp_path), "AGENT_PLATFORM_ROOT": str(root)})
    assert done.returncode == 1 and "2個あります" in done.stderr and "--agent-dir" in done.stderr


def test_the_agent_comes_from_the_strongest_of_the_option_the_variable_and_the_root(tmp_path):
    root = tmp_path / "platform"
    add_launcher(root, "main")
    env = {"HOME": str(tmp_path), "AGENT_PLATFORM_ROOT": str(root),
           "ARK_ROOT": str(tmp_path / "from-variable"), "AREA_GUARD_STATE": str(tmp_path / "marks")}
    assert placed(where(env))["agent"] == str(tmp_path / "from-variable")
    assert placed(where(env, "--agent-dir", str(tmp_path / "from-option"), "nothing"))["agent"] == str(tmp_path / "from-option")
    assert placed(where(env))["marks"] == str(tmp_path / "marks")


def test_a_missing_launcher_is_named_with_the_places_to_pass_it(tabs):
    assert tabs.run("new", "x", str(tabs.work / "none"), ARK_ROOT=str(tabs.work / "nowhere")) != 0
    assert "エージェントの起動 script が見つかりません" in tabs.err and "--agent-dir" in tabs.err


def test_the_shim_hands_everything_to_the_script(tabs):
    done = subprocess.run([str(SHIM), "--agent-dir", str(tabs.agent), "children", "--summary"], capture_output=True, text=True,
                          timeout=60, env=tabs.env(PWA_SID=""))
    assert done.returncode == 0 and "children: UNKNOWN" in done.stdout


def test_the_shim_through_a_link_still_finds_the_script(tabs, tmp_path):
    link = tmp_path / "tabs"
    link.symlink_to(SHIM)
    done = subprocess.run([str(link)], capture_output=True, text=True, timeout=60, env=tabs.env())
    assert done.returncode == 2 and "tabs [--agent-dir" in done.stderr


# --- 子のタブを立てる -------------------------------------------------------------------

def test_new_opens_a_child_and_keeps_the_task_in_its_note(tabs, tmp_path):
    task = tmp_path / "task.txt"
    task.write_text("parser を直して\n\n終わったら report done\n", encoding="utf-8")
    assert tabs.run("new", "SUB: parser", str(task)) == 0
    assert "立てました: ses_new (SUB: parser)" in tabs.out
    [call] = tabs.backend.called("POST", "/sessions/ses_parent/children")
    assert call["form"]["text"].startswith("<child-start>\ntier=normal\n</child-start>\n\nparser を直して")
    assert call["form"]["title"] == "SUB: parser"
    note = (tabs.agent / "notes/ses_new.md").read_text(encoding="utf-8")
    assert "- 状態: 作業中" in note and "- 親のタブ: ses_parent" in note and "parser を直して" in note and "\n## 引き継ぎ" in note


def test_a_child_does_not_open_a_child(tabs, tmp_path):
    task = tmp_path / "task.txt"
    task.write_text("x", encoding="utf-8")
    assert tabs.run("new", "x", str(task), ARK_CHILD="1") == 1
    assert "子のタブからは" in tabs.err and tabs.backend.calls == []


def test_a_refused_new_says_why_and_leaves_no_note(tabs, tmp_path):
    task = tmp_path / "task.txt"
    task.write_text("x", encoding="utf-8")
    tabs.backend.answers["children"] = 409
    assert tabs.run("new", "x", str(task)) == 1
    assert "child_session_limit" in tabs.err and not (tabs.agent / "notes/ses_new.md").exists()


# --- 子の一覧・報告・閉じる -------------------------------------------------------------

@pytest.fixture
def family(tabs):
    tabs.backend.tabs = [
        {"id": "ses_parent", "title": "main", "child": False, "parent_id": None},
        {"id": "ses_a", "title": "A", "child": True, "parent_id": "ses_parent"},
        {"id": "ses_b", "title": "B", "child": True, "parent_id": "ses_parent"},
        {"id": "ses_fork", "title": "fork", "child": False, "parent_id": "ses_parent"},
        {"id": "ses_other", "title": "other's", "child": True, "parent_id": "ses_someone"},
    ]
    tabs.note("ses_a", "# A\n\n- 状態: 作業中\n")
    tabs.note("ses_b", "# B\n\n- 状態: 完了\n")
    return tabs


def test_children_counts_only_my_children_by_state(family):
    assert family.run("children", "--summary") == 0
    assert "children: 2 (作業中 1 / 完了 1 / 詰まり 0 / 静か 1)" in family.out
    family.run("children")
    assert "ses_a  作業中" in family.out and "ses_b  完了" in family.out and "ses_other" not in family.out


def test_a_working_child_without_claude_is_marked_quiet_and_a_finished_one_is_not(family):
    family.run("children")
    lines = {line.split()[0]: line for line in family.out.splitlines()}
    assert "claude なし" in lines["ses_a"] and "静か" in lines["ses_a"] and "静か" not in lines["ses_b"]


def test_a_working_child_with_claude_is_not_quiet(family):
    sessions = family.home / ".claude/sessions"
    sessions.mkdir()
    (sessions / "1.json").write_text(
        json.dumps({"sessionId": "s-a", "pid": os.getpid(), "tmux": "pwa-ses_a:0", "status": "busy"}), encoding="utf-8")
    family.run("children", "--summary")
    assert "children: 2 (作業中 1 / 完了 1 / 詰まり 0 / 静か 0)" in family.out


def test_outside_a_pwa_tab_children_says_unknown(family):
    assert family.run("children", "--summary", PWA_SID="") == 0
    assert "children: UNKNOWN" in family.out


def test_report_is_only_for_children_and_changes_the_note_only_when_it_arrives(family, tmp_path):
    result = tmp_path / "result.txt"
    result.write_text("直しました。 branch は feature/parser\n", encoding="utf-8")
    note = family.agent / "notes/ses_a.md"
    assert family.run("report", "done", str(result)) == 1 and "子のタブ" in family.err

    family.backend.answers["send"] = 403
    assert family.run("report", "done", str(result), PWA_SID="ses_a", ARK_CHILD="1", PWA_NOTE=str(note)) == 1
    assert "- 状態: 作業中" in note.read_text(encoding="utf-8")

    family.backend.answers.clear()
    assert family.run("report", "done", str(result), PWA_SID="ses_a", ARK_CHILD="1", PWA_NOTE=str(note)) == 0
    [call] = family.backend.called("POST", "/agent-messages")
    assert call["form"]["to"] == "ses_parent" and call["form"]["from"] == "ses_a"
    assert "(完了)" in call["form"]["text"] and "feature/parser" in call["form"]["text"]
    assert "- 状態: 完了" in note.read_text(encoding="utf-8")


def test_close_closes_only_my_finished_children_unless_forced(family):
    assert family.run("close", "ses_other") == 1 and "このタブが立てた子ではありません" in family.err
    assert family.backend.called("DELETE", "/sessions/ses_other") == []
    assert family.run("close", "ses_a") == 1 and "まだ作業中" in family.err
    assert family.backend.called("DELETE", "/sessions/ses_a") == []
    assert family.run("close", "ses_b") == 0
    assert family.backend.called("DELETE", "/sessions/ses_b") and not (family.agent / "notes/ses_b.md").exists()
    assert family.run("close", "ses_a", "--force") == 0 and family.backend.called("DELETE", "/sessions/ses_a")


# --- 起動し直し -------------------------------------------------------------------------

def test_a_child_rolls_over_only_after_writing_what_the_next_conversation_continues_from(family):
    note = family.note("ses_c", "# C\n\n- 状態: 作業中\n\n## 渡された仕事\n\nx\n\n## 引き継ぎ\n\n(まだ無し)\n")
    roll = lambda: family.run("rollover", "continue", PWA_SID="ses_c", ARK_CHILD="1", PWA_NOTE=str(note))  # noqa: E731
    family.record.write_text("", encoding="utf-8")

    assert roll() == 1 and "タブのメモ" in family.err
    family.used("Edit", note)
    assert roll() == 1 and "が空です" in family.err
    assert not family.backend.called("POST", "/sessions/ses_c/rollover")

    note.write_text("# C\n\n- 状態: 作業中\n\n## 渡された仕事\n\nx\n\n## 引き継ぎ\n\n- test を 3 本足した所まで\n", encoding="utf-8")
    roll()
    [call] = family.backend.called("POST", "/sessions/ses_c/rollover")
    assert "tier=normal" in call["form"]["text"]


def git(folder: Path, *args: str) -> None:
    # この機械の git の設定 (= 全体の hook の入口) を読まない
    env = {**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.com",
           "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@example.com",
           "GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": os.devnull}
    subprocess.run(["git", "-C", str(folder), *args], check=True, capture_output=True, env=env)


def test_a_conversation_rolls_over_once_its_journal_is_written_and_committed(tabs):
    tabs.backend.answers.clear()
    # 繋がらない port の backend: 締めが済んだ時は、 頼みに行く所まで進んで接続で止まる
    run = lambda: tabs.run("rollover", "continue", "--tier", "normal", PWA_PORT="1")  # noqa: E731
    git(tabs.agent.parent, "init", "-q", "--bare", "remote.git")
    git(tabs.agent, "init", "-q", "-b", "master")
    git(tabs.agent, "remote", "add", "origin", str(tabs.agent.parent / "remote.git"))
    journals = tabs.agent / "journal/2026-01-01"
    journals.mkdir(parents=True)
    old, new = journals / "session-01.md", journals / "session-02.md"
    old.write_text("# 前の会話\n\n## 入れ替えの時点\n\n- 前の会話の物\n", encoding="utf-8")
    git(tabs.agent, "add", "-A")
    git(tabs.agent, "commit", "-qm", "init")
    tabs.record.write_text("", encoding="utf-8")

    assert run() == 1 and "まだ起動し直せません" in tabs.err and "journal をまだ書いていない" in tabs.err
    tabs.used("Read", old)
    assert run() == 1 and "journal をまだ書いていない" in tabs.err

    new.write_text("# この会話\n\n## やったこと\n", encoding="utf-8")
    tabs.used("Write", new)
    assert run() == 1 and "## 入れ替えの時点" in tabs.err and "session-02.md" in tabs.err

    new.write_text(new.read_text(encoding="utf-8") + "\n## 入れ替えの時点\n\n- 引き金: 60%\n", encoding="utf-8")
    tabs.used("Edit", new)
    assert run() == 1 and "commit していません" in tabs.err

    git(tabs.agent, "add", str(new))
    git(tabs.agent, "commit", "-qm", "journal")
    # push していなくても、 commit 済みなら backend へ頼みに行く (= push は次の会話の締めが運ぶ)
    assert run() == 1 and "まだ起動し直せません" not in tabs.err and "起動し直せません" in tabs.err

    # 別のタブの書きかけには止められない
    (journals / "session-03.md").write_text("another tab is writing this\n", encoding="utf-8")
    assert run() == 1 and "まだ起動し直せません" not in tabs.err and "起動し直せません" in tabs.err


def test_a_journal_in_a_repo_without_a_remote_needs_only_the_commit(tabs):
    local = tabs.agent / "projects/local-tier"
    (local / "journal/2026-01-01").mkdir(parents=True)
    git(local, "init", "-q", "-b", "master")
    journal = local / "journal/2026-01-01/session-01.md"
    journal.write_text("# この会話\n\n## 入れ替えの時点\n\n- 引き金: 60%\n", encoding="utf-8")
    tabs.record.write_text("", encoding="utf-8")
    tabs.used("Write", journal)
    run = lambda: tabs.run("rollover", "continue", "--tier", "normal", PWA_PORT="1")  # noqa: E731
    assert run() == 1 and "commit していません" in tabs.err
    git(local, "add", "-A")
    git(local, "commit", "-qm", "journal")
    assert run() == 1 and "まだ起動し直せません" not in tabs.err and "起動し直せません" in tabs.err
    git(local, "remote", "add", "origin", str(tabs.work / "remote.git"))
    assert run() == 1 and "まだ起動し直せません" not in tabs.err and "起動し直せません" in tabs.err


# --- 一覧の伏せ方 -----------------------------------------------------------------------

GUARD_SCAN = Path.home() / ".git-hooks/scanners/corpus-scan.py"


@pytest.mark.skipif(not GUARD_SCAN.is_file(), reason="番人の corpus-scan.py が無い機械")
def test_the_listing_hides_a_tab_working_in_a_boundary_this_tab_does_not_know(tmp_path, monkeypatch):
    home = tmp_path / "home"
    (home / ".git-hooks/scanners").mkdir(parents=True)
    guard, marks = tmp_path / "guard", tmp_path / "marks"
    for folder in (guard, marks, tmp_path / "company/client-a/work", tmp_path / "company/hub", tmp_path / "agent"):
        folder.mkdir(parents=True, exist_ok=True)
    (home / ".git-hooks/scanners/corpus-scan.py").write_text(GUARD_SCAN.read_text(encoding="utf-8"), encoding="utf-8")
    (guard / "areas.txt").write_text(f"company {tmp_path}/company\nclient-a {tmp_path}/company/client-a\n", encoding="utf-8")
    (marks / "s-client.json").write_text('{"areas": ["client-a"]}', encoding="utf-8")
    (marks / "s-normal.json").write_text('{"areas": []}', encoding="utf-8")
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("GUARD_CONFIG_DIR", str(guard))
    monkeypatch.setenv("AREA_GUARD_STATE", str(marks))

    spec = importlib.util.spec_from_file_location("tabs_listing", TABS)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    work = tmp_path
    assert module.works_unknown("s-normal", work / "company/client-a/work") is True
    assert module.works_unknown("s-normal", work / "agent") is False
    assert module.works_unknown("s-client", work / "company/client-a/work") is False
    assert module.works_unknown("s-client", work / "company/hub") is False
    assert module.works_unknown(None, work / "agent") is True
    assert module.works_unknown("s-normal", None) is False
