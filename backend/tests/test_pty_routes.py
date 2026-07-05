"""pty_routes.py の送信確認カウンタの unit test。

slash command (= /deep-research 等) は JSONL に素プロンプト行ではなく
`<command-name>...` の harness XML 行として書かれる。 送信確認は素プロンプトと
slash で別カウンタを使う (= 素は _count_user_prompts、 slash は _count_command_lines)。
両者が互いに相手の行を取り違えないことを担保する。
"""
import json

import backend.terminal.routes as pr
import backend.terminal.session_resolver as psr


def _write_jsonl(path, lines):
    path.write_text("\n".join(json.dumps(line) for line in lines) + "\n")


def _user_str(content):
    return {"type": "user", "message": {"role": "user", "content": content}}


def test_count_user_prompts_counts_plain_text(tmp_path):
    p = tmp_path / "a.jsonl"
    _write_jsonl(p, [_user_str("こんにちは"), _user_str("二つ目")])
    assert pr._count_user_prompts(p)[0] == 2


def test_count_user_prompts_excludes_slash_command(tmp_path):
    # slash command の harness XML は素プロンプトとして数えない
    p = tmp_path / "a.jsonl"
    _write_jsonl(p, [
        _user_str("素プロンプト"),
        _user_str("<command-name>/deep-research</command-name>"),
        _user_str("<command-args>query</command-args>"),
    ])
    assert pr._count_user_prompts(p)[0] == 1


def test_count_command_lines_counts_command_name(tmp_path):
    # command-name 行だけを数える (= command-args / 素プロンプトは対象外)
    p = tmp_path / "a.jsonl"
    _write_jsonl(p, [
        _user_str("素プロンプト"),
        _user_str("<command-name>/deep-research</command-name>"),
        _user_str("<command-args>query</command-args>"),
        _user_str("<command-name>/clear</command-name>"),
    ])
    assert pr._count_command_lines(p)[0] == 2


def test_count_command_lines_zero_for_plain(tmp_path):
    p = tmp_path / "a.jsonl"
    _write_jsonl(p, [_user_str("ただの発言")])
    assert pr._count_command_lines(p)[0] == 0


def test_counts_skip_sidechain_and_meta(tmp_path):
    p = tmp_path / "a.jsonl"
    _write_jsonl(p, [
        {"type": "user", "isSidechain": True, "message": {"content": "<command-name>/x</command-name>"}},
        {"type": "user", "isMeta": True, "message": {"content": "素"}},
    ])
    assert pr._count_user_prompts(p)[0] == 0
    assert pr._count_command_lines(p)[0] == 0


def test_counts_missing_file(tmp_path):
    assert pr._count_user_prompts(tmp_path / "nope.jsonl")[0] == 0
    assert pr._count_command_lines(tmp_path / "nope.jsonl")[0] == 0


# --- autoresume (= Mac/backend 再起動跨ぎで前回 claude session を継続) ---

import time
import backend.jsonl.watcher as jsonl_watcher


def _set_binding(monkeypatch, sid, jsonl_path, confirmed=True):
    """jsonl_watcher.list_bindings を monkeypatch して 1 件返す。"""
    monkeypatch.setattr(jsonl_watcher, "list_bindings", lambda: {
        sid: {
            "claude_pid": None,
            "claude_cwd": None,
            "start_time": None,
            "jsonl_path": str(jsonl_path) if jsonl_path else None,
            "confirmed": confirmed,
        }
    })


def test_last_resumable_returns_stem_for_fresh_jsonl(tmp_path, monkeypatch):
    jsonl = tmp_path / "abc-123.jsonl"
    jsonl.write_text("")  # 今この瞬間に作成 = mtime 新鮮
    _set_binding(monkeypatch, "ses_x", jsonl)
    assert pr._last_resumable_claude_sid("ses_x") == "abc-123"


def test_last_resumable_none_for_stale_jsonl(tmp_path, monkeypatch):
    jsonl = tmp_path / "old.jsonl"
    jsonl.write_text("")
    # 31 日前に倒して age 超過 → resume せず
    stale = time.time() - 31 * 86400
    import os
    os.utime(jsonl, (stale, stale))
    _set_binding(monkeypatch, "ses_x", jsonl)
    assert pr._last_resumable_claude_sid("ses_x") is None


def test_last_resumable_none_for_missing_jsonl(tmp_path, monkeypatch):
    # binding は残ってるけど実ファイルが消えてる (= claude cleanup / 手動削除)
    _set_binding(monkeypatch, "ses_x", tmp_path / "gone.jsonl")
    assert pr._last_resumable_claude_sid("ses_x") is None


def test_last_resumable_none_for_unconfirmed_binding(tmp_path, monkeypatch):
    jsonl = tmp_path / "ok.jsonl"
    jsonl.write_text("")
    _set_binding(monkeypatch, "ses_x", jsonl, confirmed=False)
    assert pr._last_resumable_claude_sid("ses_x") is None


def test_resolve_launch_alias_wraps_alias_with_autoresume(tmp_path, monkeypatch):
    # bindings に最終 claude_sid あり → autoresume の `claude --resume <id>` を単独で返す
    jsonl = tmp_path / "sess-fresh.jsonl"
    jsonl.write_text("")
    _set_binding(monkeypatch, "ses_x", jsonl)
    monkeypatch.setattr(psr, "AGENTS", {"agent_x": {"launch_alias": "my_alias"}})
    monkeypatch.setattr(psr, "CLAUDE_PATH", "/usr/local/bin/claude")
    monkeypatch.setattr(psr, "sessions_meta", {
        "ses_x": type("M", (), {"agent_id": "agent_x", "resume_session_id": None})()
    })
    result = pr._resolve_launch_alias("ses_x")
    assert result == "/usr/local/bin/claude --resume sess-fresh"
    # 失敗時 fallback として通常 alias を返す (= spawn watchdog で投入)
    assert pr._resolve_autoresume_fallback("ses_x") == "my_alias"


def test_resolve_launch_alias_returns_plain_alias_when_no_resumable(tmp_path, monkeypatch):
    # bindings に該当なし → 既存通り素 alias だけ
    monkeypatch.setattr(jsonl_watcher, "list_bindings", lambda: {})
    monkeypatch.setattr(psr, "AGENTS", {"agent_x": {"launch_alias": "my_alias"}})
    monkeypatch.setattr(psr, "CLAUDE_PATH", "/usr/local/bin/claude")
    monkeypatch.setattr(psr, "sessions_meta", {
        "ses_x": type("M", (), {"agent_id": "agent_x", "resume_session_id": None})()
    })
    assert pr._resolve_launch_alias("ses_x") == "my_alias"


def test_resolve_launch_alias_fork_resume_takes_precedence(tmp_path, monkeypatch):
    # フォークの resume_session_id があれば autoresume は無視して既存フォーク経路に倒す
    jsonl = tmp_path / "ignored.jsonl"
    jsonl.write_text("")
    _set_binding(monkeypatch, "ses_x", jsonl)
    monkeypatch.setattr(psr, "AGENTS", {"agent_x": {"launch_alias": "my_alias"}})
    monkeypatch.setattr(psr, "CLAUDE_PATH", "/usr/local/bin/claude")
    monkeypatch.setattr(psr, "sessions_meta", {
        "ses_x": type("M", (), {"agent_id": "agent_x", "resume_session_id": "fork-sid-9"})()
    })
    assert pr._resolve_launch_alias("ses_x") == "/usr/local/bin/claude --resume fork-sid-9"


# ---- pty_send C-u wipe (backend-2026-07-03) ----

def test_pty_send_prepends_ctrl_u_before_text_enter(monkeypatch):
    """POST /pty/{sid}/send で text + enter が来た時、 本文送信の直前に C-u が 1 発
    tmux_send_keys で発火する (= 他 client の入力残骸 wipe)。 単発 key 送信 (Escape 等)
    には wipe 前置しない (= key の意味を壊さない)。"""
    import backend.terminal.routes as routes
    calls: list[dict] = []

    def fake_send_keys(session_id, text=None, key=None, enter=False):
        calls.append({"text": text, "key": key, "enter": enter})
        return True

    monkeypatch.setattr(routes, "tmux_send_keys", fake_send_keys)
    monkeypatch.setattr(routes, "_require_session", lambda _sid: None)
    monkeypatch.setattr(routes, "jsonl_path_for_session", lambda _sid: None)

    import asyncio
    asyncio.get_event_loop() if False else None
    asyncio.run(routes.pty_send("ses_x", {"text": "hello", "enter": True}))

    # 2026-07-06 2 段送信: 1 発目 C-u wipe、 2 発目 本文 (Enter なし)、 3 発目 Enter 単発
    # (= paste 処理完了を 300ms 待ってから確定、 救済 Enter 退役に伴う予防)。
    assert len(calls) == 3
    assert calls[0] == {"text": None, "key": "C-u", "enter": False}
    assert calls[1] == {"text": "hello", "key": None, "enter": False}
    assert calls[2] == {"text": None, "key": None, "enter": True}


def test_pty_send_no_wipe_for_key_only(monkeypatch):
    """単発 key (= Escape で停止 / AskUserQuestion typeNum 等) では wipe しない。"""
    import backend.terminal.routes as routes
    calls: list[dict] = []

    def fake_send_keys(session_id, text=None, key=None, enter=False):
        calls.append({"text": text, "key": key, "enter": enter})
        return True

    monkeypatch.setattr(routes, "tmux_send_keys", fake_send_keys)
    monkeypatch.setattr(routes, "_require_session", lambda _sid: None)
    monkeypatch.setattr(routes, "jsonl_path_for_session", lambda _sid: None)

    import asyncio
    asyncio.run(routes.pty_send("ses_x", {"key": "Escape"}))

    # key のみ = wipe しない、 1 発だけ。
    assert len(calls) == 1
    assert calls[0] == {"text": None, "key": "Escape", "enter": False}


def test_pty_send_no_wipe_for_text_without_enter(monkeypatch):
    """AskUserQuestion 自由記述 1 回目 (= text のみ、 enter なし) も wipe しない (= 本文
    確定してない状態で C-u を打つと選択肢移動の意図を壊す可能性)。"""
    import backend.terminal.routes as routes
    calls: list[dict] = []

    def fake_send_keys(session_id, text=None, key=None, enter=False):
        calls.append({"text": text, "key": key, "enter": enter})
        return True

    monkeypatch.setattr(routes, "tmux_send_keys", fake_send_keys)
    monkeypatch.setattr(routes, "_require_session", lambda _sid: None)
    monkeypatch.setattr(routes, "jsonl_path_for_session", lambda _sid: None)

    import asyncio
    asyncio.run(routes.pty_send("ses_x", {"text": "3", "enter": False}))

    assert len(calls) == 1
    assert calls[0] == {"text": "3", "key": None, "enter": False}
