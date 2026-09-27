"""launcher (= agent cfg `launcher: true`) の経路の test。

launcher の agent は、 新しい会話を最初の発話が来るまで起動せず (= 送信が来た時に
`<alias> --first-message-file <file>` を打つ)、 再開を `<alias> --resume <id>` で launcher に渡す。
launcher が会話を config dir の variant (= `<config dir>@<name>`) で起動しても、 PWA は記録の
置き場を追い、 フォーク / アカウント移し / 片付けで variant を保つ。
"""
from __future__ import annotations

import asyncio
import json
import os
import stat

import pytest

import backend.config as config
import backend.terminal.first_message as fm
from backend.terminal import input_ready
from backend.terminal import session_resolver as sr

LAUNCHER = {"launch_alias": "agent_a", "launcher": True, "cwd": "/work"}


def _run(coro):
    return asyncio.run(coro)


# --- config: variant の置き場 -------------------------------------------------------

@pytest.fixture
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    accounts = {"personal": {"env": {}}, "work": {"env": {"CLAUDE_CONFIG_DIR": str(tmp_path / ".claude-work")}}}
    cfg = tmp_path / "config.json"
    cfg.write_text(json.dumps({"agents": {"agent_a": {"cwd": "/work"}}, "accounts": accounts}))
    monkeypatch.setattr(config, "CONFIG_PATH", cfg)
    config.get_config.cache_clear()
    for d in (".claude", ".claude-work", ".claude@company", ".claude-work@company", ".claude-work@client"):
        (tmp_path / d).mkdir()
    return tmp_path


def test_projects_dirs_include_each_accounts_variants(home):
    assert config.CLAUDE_PROJECTS_DIRS == [
        home / ".claude/projects", home / ".claude@company/projects",
        home / ".claude-work/projects", home / ".claude-work@client/projects",
        home / ".claude-work@company/projects",
    ]


def test_variant_of_and_with_variant(home):
    record_dir = home / ".claude@company/projects/-work"
    assert config.variant_of(record_dir, "personal") == "@company"
    assert config.variant_of(home / ".claude/projects/-work", "personal") == ""
    # 別の account の dir は、 名前が前方一致しても variant ではない
    assert config.variant_of(home / ".claude-work/projects/-work", "personal") == ""
    assert config.with_variant(home / ".claude-work/projects/-work", "@company") == \
        home / ".claude-work@company/projects/-work"
    assert config.with_variant(home / ".claude/projects/-work", "") == home / ".claude/projects/-work"


def test_record_dirs_list_the_account_then_its_variants(home):
    assert config.record_dirs("/work", "work") == [
        home / ".claude-work/projects/-work",
        home / ".claude-work@client/projects/-work",
        home / ".claude-work@company/projects/-work",
    ]


# --- session_resolver: 起動と再開 --------------------------------------------------------

@pytest.fixture
def launcher_agent(monkeypatch):
    monkeypatch.setattr(sr, "CLAUDE_PATH", "/usr/local/bin/claude")
    monkeypatch.setattr(sr, "resolve_agent_cfg", lambda _sid: dict(LAUNCHER))
    monkeypatch.setattr(sr, "last_resumable_claude_sid", lambda _sid: None)


def test_a_new_launcher_conversation_types_nothing(launcher_agent):
    assert sr.uses_launcher("ses_x")
    assert sr.resolve_launch_alias("ses_x") is None
    assert sr.resolve_launch_alias("ses_x", prefer_fresh=True) is None


def test_autoresume_goes_through_the_launcher_without_a_fallback(launcher_agent, monkeypatch):
    monkeypatch.setattr(sr, "last_resumable_claude_sid", lambda _sid: "old-sid")
    assert sr.resolve_launch_alias("ses_x") == "agent_a --resume old-sid"
    # 失敗しても alias を打ち直さない (= pane は zsh に残り、 次の送信が起動する)
    assert sr.resolve_autoresume_fallback("ses_x") is None


def test_a_fork_resumes_through_the_launcher(launcher_agent, isolated_state):
    from backend.state import register_session  # noqa: PLC0415
    parent = register_session("agent_a", "parent")
    fork = register_session("agent_a", "fork", parent_id=parent.id, resume_session_id="fork-sid")
    assert sr.resolve_launch_alias(fork.id, prefer_fresh=True) == "agent_a --resume fork-sid"


def test_without_launcher_the_alias_and_claude_resume_stay(monkeypatch):
    monkeypatch.setattr(sr, "CLAUDE_PATH", "/usr/local/bin/claude")
    monkeypatch.setattr(sr, "resolve_agent_cfg", lambda _sid: {"launch_alias": "agent_a"})
    monkeypatch.setattr(sr, "last_resumable_claude_sid", lambda _sid: None)
    assert not sr.uses_launcher("ses_x")
    assert sr.resolve_launch_alias("ses_x") == "agent_a"
    monkeypatch.setattr(sr, "last_resumable_claude_sid", lambda _sid: "old-sid")
    assert sr.resolve_launch_alias("ses_x") == "/usr/local/bin/claude --resume old-sid"
    assert sr.first_message_command("ses_x", "/tmp/m") is None


def test_the_first_message_file_is_quoted(launcher_agent, tmp_path):
    path = tmp_path / "a b.txt"
    assert sr.first_message_command("ses_x", path) == f"agent_a --first-message-file '{path}'"


# --- first_message: 最初の送信で起動する ------------------------------------------------

@pytest.fixture
def pane(monkeypatch, tmp_path):
    """launcher の agent・claude の居ない pane・記録する tmux を用意する。"""
    keys: list[dict] = []
    state = {"claude": False, "send_ok": True}
    monkeypatch.setattr(fm, "uses_launcher", lambda _sid: True)
    monkeypatch.setattr(fm, "first_message_command", lambda _sid, path: f"agent_a --first-message-file {path}")
    monkeypatch.setattr(fm, "claude_in_pane", lambda _sid: state["claude"])

    async def _noop(_sid, **_kw):
        return None
    monkeypatch.setattr(fm, "ensure_pty_session_for", _noop)
    monkeypatch.setattr(fm, "register_claude_when_ready", _noop)

    def _keys(_sid, text=None, key=None, enter=False):
        keys.append({"text": text, "key": key, "enter": enter})
        return state["send_ok"]
    monkeypatch.setattr(fm, "tmux_send_keys", _keys)
    monkeypatch.setattr(fm, "_uploads_dir", lambda: tmp_path / "uploads")
    input_ready.forget("ses_x")
    yield keys, state
    input_ready.forget("ses_x")


def _written(keys):
    return keys[-1]["text"].split("--first-message-file ", 1)[1]


def test_the_first_message_launches_with_the_text_in_a_private_file(pane, monkeypatch, tmp_path):
    keys, _ = pane
    out = _run(fm.launch_with_first_message("ses_x", "一行目\n二行目"))
    assert out == {"ok": True, "launched": True}
    assert keys[0] == {"text": None, "key": "C-u", "enter": False}
    assert keys[1]["enter"] is True
    path = _written(keys)
    with open(path, encoding="utf-8") as fh:
        assert fh.read() == "一行目\n二行目"
    assert stat.S_IMODE(os.stat(path).st_mode) == 0o600
    # 起動中は次の送信を待たせる
    assert not input_ready.is_ready("ses_x")


def test_a_second_send_while_starting_is_not_a_second_launch(pane, monkeypatch, tmp_path):
    keys, _ = pane
    _run(fm.launch_with_first_message("ses_x", "one"))
    assert _run(fm.launch_with_first_message("ses_x", "two")) is None
    assert len(keys) == 2


def test_a_running_claude_takes_the_normal_send(pane):
    keys, state = pane
    state["claude"] = True
    assert _run(fm.launch_with_first_message("ses_x", "hello")) is None
    assert keys == []


def test_not_a_launcher_takes_the_normal_send(pane, monkeypatch):
    keys, _ = pane
    monkeypatch.setattr(fm, "uses_launcher", lambda _sid: False)
    assert _run(fm.launch_with_first_message("ses_x", "hello")) is None
    assert keys == []


def test_a_launch_that_cannot_be_typed_fails_and_stays_ready(pane, monkeypatch, tmp_path):
    keys, state = pane
    state["send_ok"] = False
    out = _run(fm.launch_with_first_message("ses_x", "hello"))
    assert out == {"ok": False, "reason": "launch_failed"}
    assert input_ready.is_ready("ses_x")


# --- 送信の入口: 最初の送信は起動に回る -----------------------------------------------------

def test_the_send_route_hands_the_first_text_to_the_launch(monkeypatch):
    import backend.terminal.routes as routes  # noqa: PLC0415
    seen: list[str] = []

    async def _launch(_sid, text):
        seen.append(text)
        return {"ok": True, "launched": True}

    async def _never(*_a, **_k):
        raise AssertionError("the text must not be typed into the pane")
    monkeypatch.setattr(routes, "_require_session", lambda _sid: None)
    monkeypatch.setattr(routes, "launch_with_first_message", _launch)
    monkeypatch.setattr(routes, "send_text_two_stage", _never)
    out = _run(routes.pty_send("ses_x", {"text": "hello", "enter": True}, idempotency_key=None))
    assert out == {"ok": True, "launched": True}
    assert seen == ["hello"]


def test_the_attachment_route_hands_text_and_paths_to_the_launch(monkeypatch):
    import backend.terminal.routes as routes  # noqa: PLC0415
    seen: list[str] = []

    async def _launch(_sid, text):
        seen.append(text)
        return {"ok": True, "launched": True}

    async def _saved(_files, _sid):
        return [{"name": "a.png", "path": "/up/a.png"}]

    async def _ready(_sid, timeout=None):
        return True
    monkeypatch.setattr(routes, "_require_session", lambda _sid: None)
    monkeypatch.setattr(routes, "launch_with_first_message", _launch)
    monkeypatch.setattr(routes, "save_to_tmp", _saved)
    monkeypatch.setattr(routes, "wait_ready", _ready)
    out = _run(routes.pty_send_with_files("ses_x", text="見て", files=[], idempotency_key=None))
    assert out == {"ok": True, "launched": True, "saved_files": [{"name": "a.png", "path": "/up/a.png"}]}
    assert seen == ["見て [添付ファイル: /up/a.png]"]


# --- 記録の置き場を追う -------------------------------------------------------------

def test_the_project_dir_follows_the_live_record(monkeypatch, isolated_state, tmp_path):
    import backend.jsonl.resolver as resolver  # noqa: PLC0415
    from backend.state import register_session  # noqa: PLC0415
    meta = register_session("agent_a", "t")
    live = tmp_path / ".claude@company/projects/-work/abc.jsonl"
    monkeypatch.setattr(resolver._pty_runner, "jsonl_path_for_session", lambda _sid: live)
    assert resolver.resolve_jsonl(meta.id, prefer="project_dir") == live.parent


def test_a_subagent_transcript_under_any_claude_config_dir_is_readable(monkeypatch, tmp_path):
    import backend.routes.files as files  # noqa: PLC0415
    monkeypatch.setattr(files, "HOME", tmp_path)
    for d in (".claude", ".claude-work", ".claude@company"):
        p = tmp_path / d / "projects/-work/sid/subagents/agent-1.jsonl"
        assert files._is_subagent_jsonl(p), d
    assert not files._is_subagent_jsonl(tmp_path / "notclaude/projects/-work/sid/subagents/agent-1.jsonl")
    assert not files._is_subagent_jsonl(tmp_path / ".claude/other/-work/sid/subagents/agent-1.jsonl")


def test_moving_a_conversation_to_another_account_keeps_its_variant(home, monkeypatch, isolated_state):
    """launcher が `~/.claude@company` で動かした会話を work へ移すと `~/.claude-work@company` に置く
    (= launcher は置き場で再開の仕方を決めるので、 移しても同じ sandbox で開く)。"""
    import backend.routes.sessions as sessions_mod  # noqa: PLC0415
    from backend.tests.test_fork import SAMPLE, _setup_fork_env  # noqa: PLC0415
    record_dir = home / ".claude@company/projects/-work"
    record_dir.mkdir(parents=True)
    chat_routes, parent, src = _setup_fork_env(record_dir, monkeypatch, isolated_state)
    parent.account_id = "personal"
    monkeypatch.setattr(sessions_mod, "AGENTS", {parent.agent_id: {"cwd": "/work"}})
    out = _run(chat_routes.fork_session(parent.id, {"target_account_id": "work"}))
    written = list((home / ".claude-work@company/projects/-work").glob("*.jsonl"))
    assert [p.stem for p in written] == [out["resume_session_id"]]
    assert list((home / ".claude-work/projects").glob("*/*.jsonl")) == []
    assert src.read_text().splitlines() == SAMPLE


def test_a_conversation_without_a_variant_moves_to_the_plain_account_dir(home, monkeypatch, isolated_state):
    import backend.routes.sessions as sessions_mod  # noqa: PLC0415
    from backend.tests.test_fork import _setup_fork_env  # noqa: PLC0415
    record_dir = home / ".claude/projects/-work"
    record_dir.mkdir(parents=True)
    chat_routes, parent, _src = _setup_fork_env(record_dir, monkeypatch, isolated_state)
    parent.account_id = "personal"
    monkeypatch.setattr(sessions_mod, "AGENTS", {parent.agent_id: {"cwd": "/work"}})
    out = _run(chat_routes.fork_session(parent.id, {"target_account_id": "work"}))
    assert [p.stem for p in (home / ".claude-work/projects/-work").glob("*.jsonl")] == [out["resume_session_id"]]


def test_claude_is_looked_for_deep_under_the_pane(monkeypatch):
    """launcher が sandbox で包むと claude は数段下に居る。"""
    import backend.terminal.pty_discover as pd  # noqa: PLC0415
    depths: list[int] = []
    monkeypatch.setattr(pd, "tmux_pane_pids", lambda _sid: [101])

    def _find(_pid, max_depth=6):
        depths.append(max_depth)
        return None
    monkeypatch.setattr(pd, "_find_claude_descendant_info", _find)
    assert pd.claude_in_pane("ses_x") is False
    assert depths == [12]
