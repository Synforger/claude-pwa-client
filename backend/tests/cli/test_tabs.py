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

REPO_ROOT = Path(__file__).resolve().parent.parent.parent.parent
TABS = REPO_ROOT / "backend" / "cli" / "tabs.py"
SHIM = REPO_ROOT / "bin" / "tabs"
SESSION = "11111111-2222-3333-4444-555555555555"

# エージェントの起動 script のうち tabs が使う 4 つ (= 階層の決め方) だけを持つ作り物
LAUNCHER = '''
import json
import os
import re
from pathlib import Path

AGENT = Path(__file__).resolve().parents[2]
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
        self.local_tabs: list[dict] = []
        # 子のタブの id → 区切りから外している理由 (= `GET /sessions/{親}/children`)。 無い子は区切りに居る (= [])
        self.holds: dict[str, list[str] | None] = {}
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
                if method == "GET" and self.path.startswith("/sessions/") and self.path.endswith("/children"):
                    if backend.answers.get("holds", 200) != 200:
                        return self.reply(backend.answers["holds"], {})
                    parent = self.path.split("/")[2]
                    return self.reply(200, {"children": [
                        {"id": t["id"], "blocked_by": backend.holds.get(t["id"], [])}
                        for t in backend.tabs if t.get("child") and t.get("parent_id") == parent]})
                if method == "GET" and self.path == "/agent-messages/local-tabs":
                    return self.reply(200, {"tabs": backend.local_tabs})
                if method == "POST" and self.path == "/tier-tabs":
                    if backend.answers.get("tier-tabs", 200) != 200:
                        return self.reply(backend.answers["tier-tabs"], {"detail": {"code": "tier_tab_exists", "message": "has one"}})
                    return self.reply(200, {"id": "ses_tier", "title": "B", "child": False, "tier_tab": "projects/B"})
                if method == "POST" and self.path.endswith("/sleep"):
                    if backend.answers.get("sleep", 200) != 200:
                        return self.reply(backend.answers["sleep"], {"detail": {
                            "code": "child_sleep_refused", "message": "no",
                            "params": {"reasons": "voice_call,wakeup_scheduled"}}})
                    return self.reply(200, {"ok": True, "already": False})
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
        (self.agent / "pages").mkdir()
        (self.agent / ".tooling/lib/claude-launch.py").write_text(LAUNCHER, encoding="utf-8")
        self.record = self.home / f".claude/projects/-agent/{SESSION}.jsonl"
        self.out = self.err = ""

    def env(self, **extra: str) -> dict[str, str]:
        base = {"PATH": os.environ["PATH"], "HOME": str(self.home), "AGENT_ROOT": str(self.agent), "PWA_SID": "ses_parent",
                "PWA_PORT": str(self.backend.port), "AGENT_TIER": "normal", "CLAUDE_CODE_SESSION_ID": SESSION,
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
        path = self.agent / "pages" / name / "memo.md"
        path.parent.mkdir(parents=True, exist_ok=True)
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

def where(env: dict[str, str], *argv: str, cwd: Path = REPO_ROOT) -> subprocess.CompletedProcess:
    """新しい process で、 tabs が決めたエージェントの folder と印の置き場を JSON で出させる (= 器の根と HOME は import の時に読まれる)。"""
    script = ("import json, sys; from backend.cli import tabs; tabs.main(sys.argv[1:]); "
              "print(json.dumps({'agent': str(tabs.agent_dir()), 'marks': str(tabs.MARKS)}))")
    return subprocess.run([sys.executable, "-c", script, *argv], cwd=cwd, capture_output=True, text=True, timeout=60,
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


def test_a_root_with_several_agents_asks_for_one_outside_them(tmp_path):
    root = tmp_path / "platform"
    add_launcher(root, "one")
    add_launcher(root, "two")
    done = where({"HOME": str(tmp_path), "AGENT_PLATFORM_ROOT": str(root)})
    assert done.returncode == 1 and "2個あります" in done.stderr and "--agent-dir" in done.stderr
    (root / "agents/three").mkdir()
    done = where({"HOME": str(tmp_path), "AGENT_PLATFORM_ROOT": str(root)}, "nothing", cwd=root / "agents/three")
    assert done.returncode == 1 and "2個あります" in done.stderr


def test_a_root_with_several_agents_gives_the_one_the_tab_works_in(tmp_path):
    root = tmp_path / "platform"
    add_launcher(root, "one")
    two = add_launcher(root, "two")
    env = {"HOME": str(tmp_path), "AGENT_PLATFORM_ROOT": str(root)}
    assert placed(where(env, "nothing", cwd=two))["agent"] == str(two)
    tier = two / "projects/P/subprojects/S"
    tier.mkdir(parents=True)
    assert placed(where(env, "nothing", cwd=tier))["agent"] == str(two)


def test_a_root_with_several_agents_finds_the_tab_s_one_through_a_link(tmp_path):
    root = tmp_path / "platform"
    add_launcher(root, "one")
    two = add_launcher(root, "two")
    link = tmp_path / "linked-platform"
    link.symlink_to(root)
    done = where({"HOME": str(tmp_path), "AGENT_PLATFORM_ROOT": str(link)}, "nothing", cwd=two)
    assert placed(done)["agent"] == str(link / "agents/two")


def test_the_agent_comes_from_the_strongest_of_the_option_the_variable_and_the_root(tmp_path):
    root = tmp_path / "platform"
    add_launcher(root, "main")
    env = {"HOME": str(tmp_path), "AGENT_PLATFORM_ROOT": str(root),
           "AGENT_ROOT": str(tmp_path / "from-variable"), "AREA_GUARD_STATE": str(tmp_path / "marks")}
    assert placed(where(env))["agent"] == str(tmp_path / "from-variable")
    assert placed(where(env, "--agent-dir", str(tmp_path / "from-option"), "nothing"))["agent"] == str(tmp_path / "from-option")
    assert placed(where(env))["marks"] == str(tmp_path / "marks")


def test_a_missing_launcher_is_named_with_the_places_to_pass_it(tabs):
    assert tabs.run("new", "x", str(tabs.work / "none"), AGENT_ROOT=str(tabs.work / "nowhere")) != 0
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
    note = (tabs.agent / "pages/ses_new/memo.md").read_text(encoding="utf-8")
    assert "- 状態: 作業中" in note and "- 親のタブ: ses_parent" in note and "parser を直して" in note and "\n## 引き継ぎ" in note


def test_a_child_does_not_open_a_child(tabs, tmp_path):
    task = tmp_path / "task.txt"
    task.write_text("x", encoding="utf-8")
    assert tabs.run("new", "x", str(task), AGENT_CHILD="1") == 1
    assert "子のタブからは" in tabs.err and tabs.backend.calls == []


def test_a_refused_new_says_why_and_leaves_no_note(tabs, tmp_path):
    task = tmp_path / "task.txt"
    task.write_text("x", encoding="utf-8")
    tabs.backend.answers["children"] = 409
    assert tabs.run("new", "x", str(task)) == 1
    assert "child_session_limit" in tabs.err and not (tabs.agent / "pages/ses_new/memo.md").exists()


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


def running_claude(family, tab: str, status: str, number: int = 1) -> None:
    """A claude of the given status runs in the tab (= the record Claude Code keeps for a live claude)."""
    sessions = family.home / ".claude/sessions"
    sessions.mkdir(exist_ok=True)
    (sessions / f"{number}.json").write_text(
        json.dumps({"sessionId": f"s-{tab}", "pid": os.getpid(), "tmux": f"pwa-{tab}:0", "status": status}), encoding="utf-8")


def lines_by_tab(family) -> dict[str, str]:
    family.run("children")
    return {line.split()[0]: line for line in family.out.splitlines()}


def test_children_counts_only_my_children_by_state(family):
    running_claude(family, "ses_a", "idle")
    assert family.run("children", "--summary") == 0
    assert "children: 2 (作業中 1 / 完了 1 / 詰まり 0 / 静か 1)" in family.out
    family.run("children")
    assert "ses_a  作業中" in family.out and "ses_b  完了" in family.out and "ses_other" not in family.out


def test_the_claude_column_says_answering_waiting_asleep_or_no_claude(family):
    family.backend.tabs.insert(3, {"id": "ses_c", "title": "C", "child": True, "parent_id": "ses_parent"})
    family.backend.tabs.insert(4, {"id": "ses_d", "title": "D", "child": True, "parent_id": "ses_parent", "asleep": True})
    for tab in ("ses_c", "ses_d"):
        family.note(tab, f"# {tab}\n\n- 状態: 作業中\n")
    running_claude(family, "ses_a", "busy", 1)
    running_claude(family, "ses_c", "idle", 2)
    lines = lines_by_tab(family)
    assert lines["ses_a"].split("  ")[2] == "作業中"
    assert lines["ses_c"].split("  ")[2] == "入力待ち"
    assert lines["ses_d"].split("  ")[2] == "眠り"
    assert lines["ses_b"].split("  ")[2] == "Claude なし"


def test_a_working_child_whose_claude_waits_is_marked_as_stopped_without_a_report(family):
    running_claude(family, "ses_a", "idle")
    lines = lines_by_tab(family)
    assert "入力待ち" in lines["ses_a"] and "← 報告なしで止まっている" in lines["ses_a"]
    assert "静か" not in family.out


def test_a_child_waiting_for_its_background_command_is_not_marked_as_stopped(family):
    """Claude Code wakes a child itself when a command it started in the background ends: such a child holds work."""
    running_claude(family, "ses_a", "idle")
    family.backend.holds["ses_a"] = ["processes_running"]
    lines = lines_by_tab(family)
    assert lines["ses_a"].split("  ")[2] == "裏の仕事待ち" and "報告なしで" not in lines["ses_a"]
    family.run("children", "--summary")
    assert "静か 0" in family.out


def test_the_judgement_saying_a_turn_is_open_reads_as_answering(family):
    running_claude(family, "ses_a", "idle")
    family.backend.holds["ses_a"] = ["turn_open"]
    assert lines_by_tab(family)["ses_a"].split("  ")[2] == "作業中"


def test_without_the_backends_judgement_a_quiet_claude_is_not_called_stopped(family):
    running_claude(family, "ses_a", "idle")
    family.backend.answers["holds"] = 500
    lines = lines_by_tab(family)
    assert lines["ses_a"].split("  ")[2] == "裏の仕事待ち" and "報告なしで" not in lines["ses_a"]


def test_only_a_waiting_claude_of_a_working_memo_is_marked(family):
    """Asleep, no claude, answering, and a child that has reported are not stopped without a report."""
    family.backend.tabs[1]["asleep"] = True
    assert "報告なしで" not in lines_by_tab(family)["ses_a"]                  # asleep, memo working
    family.backend.tabs[1]["asleep"] = False
    assert "報告なしで" not in lines_by_tab(family)["ses_a"]                  # no claude, memo working
    running_claude(family, "ses_a", "busy")
    assert "報告なしで" not in lines_by_tab(family)["ses_a"]                  # answering
    running_claude(family, "ses_b", "idle", 2)
    assert "報告なしで" not in lines_by_tab(family)["ses_b"]                  # waiting, but its memo says done


def test_a_working_child_with_claude_answering_is_not_counted_as_quiet(family):
    running_claude(family, "ses_a", "busy")
    family.run("children", "--summary")
    assert "children: 2 (作業中 1 / 完了 1 / 詰まり 0 / 静か 0)" in family.out


def test_a_working_child_without_claude_is_not_counted_as_quiet(family):
    family.run("children", "--summary")
    assert "children: 2 (作業中 1 / 完了 1 / 詰まり 0 / 静か 0)" in family.out


def test_outside_a_pwa_tab_children_says_unknown(family):
    assert family.run("children", "--summary", PWA_SID="") == 0
    assert "children: UNKNOWN" in family.out


def test_report_is_only_for_children_and_changes_the_note_only_when_it_arrives(family, tmp_path):
    result = tmp_path / "result.txt"
    result.write_text("直しました。 branch は feature/parser\n", encoding="utf-8")
    note = family.agent / "pages/ses_a/memo.md"
    assert family.run("report", "done", str(result)) == 1 and "子のタブ" in family.err

    family.backend.answers["send"] = 403
    assert family.run("report", "done", str(result), PWA_SID="ses_a", AGENT_CHILD="1", PWA_NOTE=str(note)) == 1
    assert "- 状態: 作業中" in note.read_text(encoding="utf-8")

    family.backend.answers.clear()
    assert family.run("report", "done", str(result), PWA_SID="ses_a", AGENT_CHILD="1", PWA_NOTE=str(note)) == 0
    [call] = family.backend.called("POST", "/agent-messages")
    assert call["form"]["to"] == "ses_parent" and call["form"]["from"] == "ses_a"
    assert "(完了)" in call["form"]["text"] and "feature/parser" in call["form"]["text"]
    assert "- 状態: 完了" in note.read_text(encoding="utf-8")


def test_a_child_started_before_memos_moved_reports_into_the_memo_children_reads(family, tmp_path):
    """A child started with the old `PWA_NOTE` (whose memo has since moved to `pages/`) still marks the memo that
    `children` and `close` read."""
    result = tmp_path / "result.txt"
    result.write_text("done\n", encoding="utf-8")
    stale = family.agent / "notes/ses_a.md"
    assert family.run("report", "done", str(result), PWA_SID="ses_a", AGENT_CHILD="1", PWA_NOTE=str(stale)) == 0
    assert "- 状態: 完了" in (family.agent / "pages/ses_a/memo.md").read_text(encoding="utf-8")
    assert not stale.exists()
    family.run("children")
    assert "完了" in family.out


def test_close_closes_only_my_finished_children_unless_forced(family):
    assert family.run("close", "ses_other") == 1 and "このタブが立てた子ではありません" in family.err
    assert family.backend.called("DELETE", "/sessions/ses_other") == []
    assert family.run("close", "ses_a") == 1 and "まだ作業中" in family.err
    assert family.backend.called("DELETE", "/sessions/ses_a") == []
    assert family.run("close", "ses_b") == 0
    # the backend clears the memo when it closes a child (= `terminal/child_folder.py`); the command only asks it to
    assert family.backend.called("DELETE", "/sessions/ses_b")
    assert family.run("close", "ses_a", "--force") == 0 and family.backend.called("DELETE", "/sessions/ses_a")


def test_sleep_puts_only_my_own_children_to_sleep(family):
    assert family.run("sleep", "ses_other") == 1 and "このタブが立てた子ではありません" in family.err
    assert not [c for c in family.backend.calls if c["path"].endswith("/sleep")]
    assert family.run("sleep", "ses_b") == 0 and "眠らせました: ses_b" in family.out
    assert family.backend.called("POST", "/sessions/ses_parent/children/ses_b/sleep")


def test_sleep_names_why_a_child_was_left_awake(family):
    family.backend.answers["sleep"] = 409
    assert family.run("sleep", "ses_b") == 1
    assert "ses_b を眠らせられません: 声の通話の最中です / 起こす予約があります" in family.err


def test_children_shows_a_sleeping_child_as_asleep(family):
    family.backend.tabs[2]["asleep"] = True
    family.run("children")
    lines = {line.split()[0]: line for line in family.out.splitlines()}
    assert "眠り" in lines["ses_b"] and "Claude なし" in lines["ses_a"]


# --- 起動し直し -------------------------------------------------------------------------

def test_a_child_rolls_over_only_after_writing_what_the_next_conversation_continues_from(family):
    note = family.note("ses_c", "# C\n\n- 状態: 作業中\n\n## 渡された仕事\n\nx\n\n## 引き継ぎ\n\n(まだ無し)\n")
    roll = lambda: family.run("rollover", "continue", PWA_SID="ses_c", AGENT_CHILD="1", PWA_NOTE=str(note))  # noqa: E731
    family.record.write_text("", encoding="utf-8")

    assert roll() == 1 and "タブのメモ" in family.err
    family.used("Edit", note)
    assert roll() == 1 and "が空です" in family.err
    assert not family.backend.called("POST", "/sessions/ses_c/rollover")

    note.write_text("# C\n\n- 状態: 作業中\n\n## 渡された仕事\n\nx\n\n## 引き継ぎ\n\n- test を 3 本足した所まで\n", encoding="utf-8")
    roll()
    [call] = family.backend.called("POST", "/sessions/ses_c/rollover")
    assert "tier=normal" in call["form"]["text"]


def test_a_child_started_before_memos_moved_rolls_over_from_the_moved_memo(family):
    note = family.note("ses_c", "# C\n\n- 状態: 作業中\n\n## 渡された仕事\n\nx\n\n## 引き継ぎ\n\n- ここまで\n")
    stale = family.agent / "notes/ses_c.md"
    family.record.write_text("", encoding="utf-8")
    family.used("Edit", note)
    family.run("rollover", "continue", PWA_SID="ses_c", AGENT_CHILD="1", PWA_NOTE=str(stale))
    assert family.backend.called("POST", "/sessions/ses_c/rollover"), family.err


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
    # 照合は自分の実体の在処から部品 (= 置き場の表) を辿るので、 写さずに本物への link を張る (= この機械の
    # `~/.git-hooks/scanners/` と同じ形)。
    (home / ".git-hooks/scanners" / GUARD_SCAN.name).symlink_to(GUARD_SCAN.resolve())
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


# --- 階層のタブ -----------------------------------------------------------------------------------------

def test_open_asks_the_backend_for_the_tier_s_tab_of_this_agent(tabs):
    assert tabs.run("open", "projects/B") == 0
    [call] = tabs.backend.called("POST", "/tier-tabs")
    assert call["form"] == {"agent_dir": str(tabs.agent), "tier": "projects/B"}
    assert "置きました: ses_tier (B)" in tabs.out


def test_open_names_the_backend_s_refusal(tabs):
    tabs.backend.answers["tier-tabs"] = 409
    assert tabs.run("open", "projects/B") == 1
    assert "tier_tab_exists" in tabs.err


def test_the_listing_shows_a_placed_tier_tab_before_its_claude_starts(tabs):
    tabs.backend.tabs = [
        {"id": "ses_parent", "title": "main", "agent_id": "agent_a", "child": False, "parent_id": None},
        {"id": "ses_placed", "title": "P", "agent_id": "agent_a", "child": False, "parent_id": None,
         "tier_tab": "projects/P"},
        {"id": "ses_theirs", "title": "Q", "agent_id": "agent_b", "child": False, "parent_id": None,
         "tier_tab": "normal"},
        {"id": "ses_hand", "title": "hand", "agent_id": "agent_a", "child": False, "parent_id": None,
         "tier": "projects/P"},
        {"id": "ses_fresh", "title": "desk", "agent_id": "agent_a", "child": False, "parent_id": None},
    ]
    tabs.backend.local_tabs = [
        {"id": "ses_placed", "reachable": True, "conversation": None},
        {"id": "ses_theirs", "reachable": True, "conversation": None},
        {"id": "ses_hand", "reachable": True, "conversation": "conv-hand"},
        {"id": "ses_fresh", "reachable": False, "conversation": None},
    ]
    assert tabs.run("list") == 0
    lines = {line.split()[0]: line for line in tabs.out.splitlines() if line.strip()}
    assert lines["ses_placed"].split("  ") == ["ses_placed", "projects/P", "口座=personal", "未起動", "境界=なし", "P"]
    assert lines["ses_theirs"].split("  ")[1] == "別の agent"
    # a tab the operator opened, with no claude right now, is told apart from a tab that does not exist
    assert lines["ses_hand"].split("  ") == ["ses_hand", "projects/P", "口座=personal", "未起動", "境界=なし", "hand"]
    # no tier: where it works cannot be checked, so its name stays hidden
    assert lines["ses_fresh"].split("  ") == ["ses_fresh", "別の境界", "口座=personal", "起こせない", "境界=なし", "(別の境界のタブ)"]


def test_the_listing_tells_a_tab_put_to_sleep_from_one_that_never_started(tabs):
    tabs.backend.tabs = [
        {"id": "ses_parent", "title": "main", "agent_id": "agent_a", "child": False, "parent_id": None},
        {"id": "ses_nap", "title": "nap", "agent_id": "agent_a", "child": False, "parent_id": None, "tier": "projects/P"},
        {"id": "ses_new", "title": "new", "agent_id": "agent_a", "child": False, "parent_id": None, "tier": "projects/P"},
    ]
    tabs.backend.local_tabs = [
        {"id": "ses_nap", "reachable": True, "conversation": "conv-nap", "asleep": True},
        {"id": "ses_new", "reachable": True, "conversation": None, "asleep": False},
    ]
    assert tabs.run("list") == 0
    lines = {line.split()[0]: line for line in tabs.out.splitlines() if line.strip()}
    assert lines["ses_nap"].split("  ")[3] == "眠り"
    assert lines["ses_new"].split("  ")[3] == "未起動"


# --- 役 (= 番人が見せてよいと答えた、 伏せたタブの階層) -------------------------------------------------

FAKE_GUARD = '''
import json
import sys
import time
from pathlib import Path

here = Path(__file__).parent
with (here / "calls.log").open("a", encoding="utf-8") as log:
    log.write(json.dumps(sys.argv[1:]) + "\\n")
if "--roles" not in sys.argv:
    sys.exit(2)
config = json.loads((here / "roles.json").read_text(encoding="utf-8"))
time.sleep(config.get("sleep_sec", 0))
if config.get("exit_code"):
    sys.exit(config["exit_code"])
for name, folder in config["roles"].items():
    print(f"{name}\\t{folder}")
if config.get("junk"):
    print("a line without a tab")
'''

# 番人の境界の照合の作り物: 秘密の境界の中で働くタブを、 このタブの知らない境界のタブにする
FAKE_SCAN = '''
from pathlib import Path


def load_areas():
    return {"secret": [Path(root) for root in %r]}


def unknown_areas(read, areas):
    return ["secret"]
'''


class RolesWorld:
    """役の試験の舞台: 見る側のタブ (= 動いている claude 付き) と、 秘密の境界の folder 2 つ、 見える folder 2 つ。"""

    def __init__(self, tabs: Tabs):
        self.tabs = tabs
        self.folder = {name: tabs.agent / "projects" / name for name in ("B", "C", "D", "Open")}
        for folder in self.folder.values():
            folder.mkdir(parents=True)
        sessions = tabs.home / ".claude/sessions"
        sessions.mkdir(parents=True)
        (sessions / "1.json").write_text(json.dumps({
            "tmux": "pwa-ses_parent:0", "sessionId": "viewer-conv", "pid": os.getpid(), "cwd": str(tabs.agent), "status": "idle"}),
            encoding="utf-8")
        self.guard = tabs.home / ".git-hooks/agent-hooks/claude-code"
        scanners = tabs.home / ".git-hooks/scanners"
        scanners.mkdir(parents=True)
        (scanners / "corpus-scan.py").write_text(FAKE_SCAN % [str(self.folder["B"]), str(self.folder["C"])], encoding="utf-8")
        self.put()

    def put(self, *rows: dict) -> None:
        """backend の一覧に、 見る側のタブと `rows` を並べる。 row は {"id", "title", "tier_tab" か "tier"}。"""
        base = {"child": False, "parent_id": None, "agent_id": "agent_a"}
        self.tabs.backend.tabs = [{**base, "id": "ses_parent", "title": "main"}, *({**base, **row} for row in rows)]
        self.tabs.backend.local_tabs = [{"id": row["id"], "reachable": True, "conversation": None} for row in rows]

    def install_guard(self, roles: dict[str, str], **config: object) -> None:
        """作り物の番人を置く。 `roles` は役の名前 → folder。 `config` は sleep_sec・exit_code・junk。"""
        self.guard.mkdir(parents=True, exist_ok=True)
        (self.guard / "peers.py").write_text(FAKE_GUARD, encoding="utf-8")
        (self.guard / "roles.json").write_text(json.dumps({"roles": roles, **config}), encoding="utf-8")

    def asked(self) -> list[list[str]]:
        log = self.guard / "calls.log"
        return [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines()] if log.is_file() else []

    def roles_asked(self) -> list[list[str]]:
        return [call for call in self.asked() if "--roles" in call]


@pytest.fixture
def world(tabs):
    return RolesWorld(tabs)


def listed(tabs: Tabs) -> dict[str, list[str]]:
    assert tabs.run("list") == 0, tabs.err
    return {line.split("  ")[0]: line.split("  ") for line in tabs.out.splitlines() if line.strip()}


def test_the_listing_names_a_hidden_tab_by_its_role_only_when_its_folder_is_the_role_s(world):
    world.put({"id": "ses_b", "title": "client B", "tier_tab": "projects/B"},
              {"id": "ses_c", "title": "client C", "tier_tab": "projects/C"},
              {"id": "ses_open", "title": "Open", "tier_tab": "projects/Open"})
    world.install_guard({"role-b": str(world.folder["B"]), "role-open": str(world.folder["Open"])})
    lines = listed(world.tabs)
    # a hidden tab keeps the hidden tier; only its name cell tells the role
    assert lines["ses_b"][1:] == ["別の境界", "口座=personal", "未起動", "境界=なし", "役=role-b"]
    # another folder: the role does not apply
    assert lines["ses_c"][1:] == ["別の境界", "口座=personal", "未起動", "境界=なし", "(別の境界のタブ)"]
    # a tab that is not hidden shows its own name, even in the folder of a role
    assert lines["ses_open"][1:] == ["projects/Open", "口座=personal", "未起動", "境界=なし", "Open"]
    # the guard is asked once, with the viewer's folder and claude session
    assert world.roles_asked() == [["--roles", "--folder", str(world.tabs.agent), "--session", "viewer-conv"]]


def test_the_listing_compares_the_role_folder_by_its_real_path(world):
    world.put({"id": "ses_b", "title": "client B", "tier_tab": "projects/B"})
    (world.tabs.work / "link").symlink_to(world.folder["B"])
    world.install_guard({"role-b": str(world.tabs.work / "link")})
    assert listed(world.tabs)["ses_b"][-1] == "役=role-b"


@pytest.mark.parametrize("guard", ["missing", "old", "failing", "junk"])
def test_without_an_answer_from_the_guard_the_listing_stays_as_it_was(world, guard):
    world.put({"id": "ses_b", "title": "client B", "tier_tab": "projects/B"})
    if guard == "old":
        world.install_guard({}, exit_code=2)
    elif guard == "failing":
        world.install_guard({"role-b": str(world.folder["B"])}, exit_code=1)
    elif guard == "junk":
        world.install_guard({}, junk=True)
    lines = listed(world.tabs)
    assert lines["ses_b"][1:] == ["別の境界", "口座=personal", "未起動", "境界=なし", "(別の境界のタブ)"]


def load_tabs_module():
    spec = importlib.util.spec_from_file_location("tabs_roles", TABS)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_a_guard_that_does_not_answer_in_time_gives_no_roles(world, monkeypatch):
    world.install_guard({"role-b": str(world.folder["B"])}, sleep_sec=30)
    monkeypatch.setenv("HOME", str(world.tabs.home))
    module = load_tabs_module()
    monkeypatch.setattr(module, "ROLES_TIMEOUT_SEC", 1)
    assert module.ask_roles(world.tabs.agent, "viewer-conv") == {}


def test_the_roles_come_back_by_name_with_real_folders_and_without_a_session_when_it_is_unknown(world, monkeypatch):
    world.install_guard({"role-b": str(world.folder["B"])}, junk=True)
    monkeypatch.setenv("HOME", str(world.tabs.home))
    module = load_tabs_module()
    assert module.ask_roles(world.tabs.agent, None) == {"role-b": str(world.folder["B"])}
    assert world.roles_asked() == [["--roles", "--folder", str(world.tabs.agent)]]
    assert module.ask_roles(None, "viewer-conv") == {}


def sent_to(tabs: Tabs) -> list[str]:
    return [call["form"]["to"] for call in tabs.backend.called("POST", "/agent-messages")]


def send(tabs: Tabs, to: str) -> int:
    body = tabs.work / "body.md"
    body.write_text("hello", encoding="utf-8")
    return tabs.run("send", to, str(body))


def test_a_tab_id_is_sent_as_it_is_without_asking_the_guard(world):
    world.put({"id": "ses_b", "title": "role-b", "tier_tab": "projects/B"})
    world.install_guard({"role-b": str(world.folder["B"])})
    assert send(world.tabs, "ses_b") == 0
    assert sent_to(world.tabs) == ["ses_b"]
    assert world.roles_asked() == []


def test_a_role_goes_to_the_only_tab_working_in_its_folder(world):
    world.put({"id": "ses_b", "title": "client B", "tier_tab": "projects/B"}, {"id": "ses_c", "title": "client C", "tier_tab": "projects/C"})
    world.install_guard({"role-b": str(world.folder["B"])})
    assert send(world.tabs, "role-b") == 0
    assert sent_to(world.tabs) == ["ses_b"]
    assert "届きました: ses_b" in world.tabs.out
    assert len(world.roles_asked()) == 1


def test_a_role_with_several_tabs_goes_to_the_tab_placed_for_its_tier(world):
    world.put({"id": "ses_hand", "title": "hand", "tier": "projects/B"},
              {"id": "ses_placed", "title": "placed", "tier_tab": "projects/B"},
              {"id": "ses_child", "title": "child", "tier": "projects/B", "child": True, "parent_id": "ses_placed"})
    world.install_guard({"role-b": str(world.folder["B"])})
    assert send(world.tabs, "role-b") == 0
    assert sent_to(world.tabs) == ["ses_placed"]


@pytest.mark.parametrize("rows", [
    [{"id": "ses_x", "title": "x", "tier": "projects/B"}, {"id": "ses_y", "title": "y", "tier": "projects/B"}],
    [{"id": "ses_x", "title": "x", "tier_tab": "projects/B"}, {"id": "ses_y", "title": "y", "tier_tab": "projects/B"}],
], ids=["no placed tab", "two placed tabs"])
def test_a_role_with_several_tabs_and_no_single_placed_one_asks_for_an_id(world, rows):
    world.put(*rows)
    world.install_guard({"role-b": str(world.folder["B"])})
    assert send(world.tabs, "role-b") == 1
    assert "agent_message_ambiguous_receiver" in world.tabs.err
    assert "id で指定してください: ses_x, ses_y" in world.tabs.err
    assert sent_to(world.tabs) == []


def test_a_role_without_a_tab_is_refused_without_the_hint_to_open_one(world):
    world.put({"id": "ses_b", "title": "client B", "tier_tab": "projects/B"})
    world.install_guard({"role-d": str(world.folder["D"])})
    assert send(world.tabs, "role-d") == 1
    assert "その役のタブが見つかりません" in world.tabs.err
    assert "tabs open" not in world.tabs.err
    assert sent_to(world.tabs) == []


def test_a_role_that_is_also_the_name_of_a_visible_tab_goes_to_neither(world):
    world.put({"id": "ses_b", "title": "client B", "tier_tab": "projects/B"},
              {"id": "ses_open", "title": "role-b", "tier_tab": "projects/Open"})
    world.install_guard({"role-b": str(world.folder["B"])})
    assert send(world.tabs, "role-b") == 1
    assert "agent_message_ambiguous_receiver" in world.tabs.err
    assert "ses_b" in world.tabs.err and "ses_open" in world.tabs.err
    assert sent_to(world.tabs) == []


def test_the_name_of_a_hidden_tab_does_not_stand_in_the_way_of_a_role(world):
    world.put({"id": "ses_b", "title": "client B", "tier_tab": "projects/B"},
              {"id": "ses_c", "title": "role-b", "tier_tab": "projects/C"})
    world.install_guard({"role-b": str(world.folder["B"])})
    assert send(world.tabs, "role-b") == 0
    assert sent_to(world.tabs) == ["ses_b"]


def test_a_name_that_is_not_a_role_is_left_to_the_backend(world):
    world.put({"id": "ses_open", "title": "Open", "tier_tab": "projects/Open"})
    world.install_guard({"role-b": str(world.folder["B"])})
    assert send(world.tabs, "Open") == 0
    assert sent_to(world.tabs) == ["Open"]


def test_without_a_guard_that_knows_roles_a_name_is_left_to_the_backend(world):
    world.put({"id": "ses_b", "title": "client B", "tier_tab": "projects/B"})
    assert send(world.tabs, "role-b") == 0
    assert sent_to(world.tabs) == ["role-b"]
    world.install_guard({}, exit_code=2)
    assert send(world.tabs, "role-b") == 0
    assert sent_to(world.tabs) == ["role-b"]
