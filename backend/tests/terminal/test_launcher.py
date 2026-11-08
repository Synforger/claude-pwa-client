"""launcher (= agent cfg `launcher: true`) の経路の test。

launcher の agent は、 新しい会話を最初の発話が来るまで起動せず (= 送信が来た時に
`<alias> --first-message-file <file>` を打つ)、 再開を `<alias> --resume <id>` で launcher に渡す。
"""
from __future__ import annotations

import asyncio
import os
import stat

import pytest

from backend.jsonl.jsonl_predicates import AGENT_MESSAGE_OPENINGS, ROLLOVER_OPENING

import backend.terminal.first_message as fm
from backend.terminal import input_ready
from backend.terminal import session_resolver as sr

LAUNCHER = {"launch_alias": "agent_a", "launcher": True, "cwd": "/work"}


def _run(coro):
    return asyncio.run(coro)


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
    from backend._common.state import register_session  # noqa: PLC0415
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
    state = {"claude": False, "send_ok": True, "typeable": True}
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

    async def _typeable(_sid, _timeout):
        return state["typeable"]
    monkeypatch.setattr(fm, "wait_until_typeable", _typeable)
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


def test_a_sleeping_tab_with_a_shell_left_reopens_its_conversation_instead_of_starting_a_new_one(pane, monkeypatch):
    # 意図: 眠ったタブの開き直しが落ちて pane に shell が残っても、 人の発話で新しい会話を始めない (= 会話が戻らなくなる)
    keys, _ = pane
    sent: list[str] = []

    class _Meta:
        def sleeping_claude_sid(self):
            return "claude-a"
    monkeypatch.setitem(fm.sessions_meta, "ses_x", _Meta())
    monkeypatch.setattr(fm, "resume_command_for", lambda _sid: "agent_a --resume claude-a")

    async def _send_when_ready(_sid, text):
        sent.append(text)
    monkeypatch.setattr(fm, "_send_when_ready", _send_when_ready)

    async def scenario():
        out = await fm.launch_with_first_message("ses_x", "hello")
        await asyncio.sleep(0)
        return out
    assert _run(scenario()) == {"ok": True, "launched": True}
    assert [k["text"] for k in keys] == [None, "agent_a --resume claude-a"]
    assert not any("--first-message-file" in (k["text"] or "") for k in keys)
    assert sent == ["hello"]


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


def test_a_pane_that_never_takes_keys_types_nothing_and_stays_ready(pane):
    keys, state = pane
    state["typeable"] = False
    out = _run(fm.launch_with_first_message("ses_x", "hello"))
    assert out == {"ok": False, "reason": "launch_failed"}
    assert keys == []
    assert input_ready.is_ready("ses_x")


def test_the_launch_waits_for_the_pane_up_to_the_input_ready_limit(pane, monkeypatch):
    keys, _ = pane
    asked: list[float] = []

    async def _typeable(_sid, timeout):
        asked.append(timeout)
        return True
    monkeypatch.setattr(fm, "wait_until_typeable", _typeable)
    assert _run(fm.launch_with_first_message("ses_x", "hello")) == {"ok": True, "launched": True}
    assert asked == [input_ready.INPUT_READY_TIMEOUT_SEC]
    assert len(keys) == 2


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

def test_the_project_dir_falls_back_to_the_live_record_when_cwd_is_unknown(monkeypatch, isolated_state, tmp_path):
    import backend._common.config as config  # noqa: PLC0415
    import backend.jsonl.resolver as resolver  # noqa: PLC0415
    from backend._common.state import register_session  # noqa: PLC0415
    monkeypatch.setattr(config, "AGENTS", {"agent_a": {}})
    meta = register_session("agent_a", "t")
    live = tmp_path / ".claude/projects/-work/abc.jsonl"
    monkeypatch.setattr(resolver._pty_runner, "jsonl_path_for_session", lambda _sid: live)
    assert resolver.resolve_jsonl(meta.id, prefer="project_dir") == live.parent


def test_a_subagent_transcript_under_any_claude_config_dir_is_readable(monkeypatch, tmp_path):
    import backend.routes.files as files  # noqa: PLC0415
    monkeypatch.setattr(files, "HOME", tmp_path)
    for d in (".claude", ".claude-work"):
        p = tmp_path / d / "projects/-work/sid/subagents/agent-1.jsonl"
        assert files._is_subagent_jsonl(p), d
    assert not files._is_subagent_jsonl(tmp_path / "notclaude/projects/-work/sid/subagents/agent-1.jsonl")
    assert not files._is_subagent_jsonl(tmp_path / ".claude/other/-work/sid/subagents/agent-1.jsonl")


def test_claude_is_looked_for_under_the_pane_at_the_default_depth(monkeypatch):
    import backend.terminal.pty_discover as pd  # noqa: PLC0415
    depths: list[int] = []
    monkeypatch.setattr(pd, "tmux_pane_pids", lambda _sid: [101])

    def _find(_pid, max_depth=6):
        depths.append(max_depth)
        return None
    monkeypatch.setattr(pd, "_find_claude_descendant_info", _find)
    assert pd.claude_in_pane("ses_x") is False
    assert depths == [6]


# --- claude の居ないタブ (= 眠りの印が無い) への発話 -------------------------------------------------------------

class _AwakeMeta:
    """眠りの印の無いタブ (= 眠らせ損ねて後から claude が終わった、 落ちた)。"""

    def __init__(self, child: bool = False):
        self.child = child
        self.tier_tab = None
        self.tier = None
        self.parent_id = None

    def sleeping_claude_sid(self):
        return None


def _awake_tab(monkeypatch, *, child: bool = False, last: str | None = "agent_a --resume claude-a") -> list[str]:
    """claude の居ない pane の、 眠りの印の無いタブを置く。 `last` はそのタブの最後の会話を開き直す命令。 → 後から打った本文。"""
    sent: list[str] = []
    monkeypatch.setitem(fm.sessions_meta, "ses_x", _AwakeMeta(child=child))
    monkeypatch.setattr(fm, "resume_command_for", lambda _sid: last)

    async def _send_when_ready(_sid, text):
        sent.append(text)
    monkeypatch.setattr(fm, "_send_when_ready", _send_when_ready)
    fm._fresh_requested.discard("ses_x")
    return sent


def _launch(text: str) -> dict | None:
    async def scenario():
        out = await fm.launch_with_first_message("ses_x", text)
        await asyncio.sleep(0)
        return out
    return _run(scenario())


def test_a_tab_whose_claude_ended_without_a_sleep_mark_reopens_its_last_conversation(pane, monkeypatch):
    # 意図: 眠らせ損ねて (= 20 秒で終わらず印を外した後に) claude が終わったタブへの発話で、 新しい会話を始めない
    keys, _ = pane
    sent = _awake_tab(monkeypatch)
    assert _launch("つづき") == {"ok": True, "launched": True}
    assert [k["text"] for k in keys] == [None, "agent_a --resume claude-a"]
    assert sent == ["つづき"]


def test_a_message_from_another_tab_also_reopens_instead_of_starting_in_a_remembered_tier(pane, monkeypatch):
    keys, _ = pane
    sent = _awake_tab(monkeypatch)
    text = f"{AGENT_MESSAGE_OPENINGS[0]}\nhello"
    assert _launch(text) == {"ok": True, "launched": True}
    assert keys[-1]["text"] == "agent_a --resume claude-a"
    assert sent == [text]


@pytest.mark.parametrize("child, text", [
    (False, f"{ROLLOVER_OPENING}\n<session-rollover phase=\"start\">\ntier=normal\nmode=wait\n</session-rollover>"),
    (True, "<child-start>\ntier=normal\n</child-start>\nthe task"),
], ids=["rollover", "child's first task"])
def test_a_rollover_and_a_child_s_first_task_start_a_new_conversation(pane, monkeypatch, child, text):
    keys, _ = pane
    _awake_tab(monkeypatch, child=child)
    assert _launch(text) == {"ok": True, "launched": True}
    assert "--first-message-file" in keys[-1]["text"]


def test_after_a_restart_the_next_message_starts_a_new_conversation_once(pane, monkeypatch):
    keys, state = pane
    _awake_tab(monkeypatch)
    fm.request_fresh("ses_x")
    assert _launch("最初から") == {"ok": True, "launched": True}
    assert "--first-message-file" in keys[-1]["text"]
    input_ready.forget("ses_x")
    assert _launch("つづき") == {"ok": True, "launched": True}
    assert keys[-1]["text"] == "agent_a --resume claude-a"


def test_a_tab_with_no_conversation_to_reopen_starts_a_new_one(pane, monkeypatch):
    keys, _ = pane
    _awake_tab(monkeypatch, last=None)
    assert _launch("hello") == {"ok": True, "launched": True}
    assert "--first-message-file" in keys[-1]["text"]
