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
