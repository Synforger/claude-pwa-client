"""session_resolver の prefer_fresh フラグ挙動テスト (= 2026-06-29 restart autoresume race 修正)。

restart 経路から autoresume を skip して通常 alias 直行する分岐 (= `prefer_fresh=True`) と、
通常経路 (= `prefer_fresh=False`) の autoresume 挙動を分けて検証する。
"""
from __future__ import annotations

from backend.terminal import session_resolver


def test_resolve_launch_alias_prefer_fresh_skips_autoresume(monkeypatch, isolated_state):
    """prefer_fresh=True なら autoresume 経路 (= `claude --resume <id>`) を踏まず通常 alias 直行。

    restart 直後の `claude --resume <直前 sid>` 重複起動 race (= rc=0 即 exit) を回避する
    分岐の core 動作。
    """
    monkeypatch.setattr(session_resolver, "CLAUDE_PATH", "/usr/local/bin/claude")
    monkeypatch.setattr(session_resolver, "resolve_agent_cfg",
                        lambda _sid: {"launch_alias": "agent_a", "cwd": "/tmp"})
    monkeypatch.setattr(session_resolver, "last_resumable_claude_sid",
                        lambda _sid: "old-claude-sid")
    # prefer_fresh=False (= 通常経路) は autoresume を返す
    assert session_resolver.resolve_launch_alias("ses_x") == \
        "/usr/local/bin/claude --resume old-claude-sid"
    # prefer_fresh=True は通常 alias 直行
    assert session_resolver.resolve_launch_alias("ses_x", prefer_fresh=True) == "agent_a"


def test_resolve_launch_alias_prefer_fresh_keeps_fork_resume(monkeypatch, isolated_state):
    """fork タブ (= resume_session_id を持つ) は prefer_fresh 関係なく `claude --resume <id>` 経路。

    fork のセマンティクスは「意図的に親文脈を引き継ぐ」 なので prefer_fresh で剥がれてはいけない。
    """
    from backend.state import register_session, sessions_meta  # noqa: PLC0415
    monkeypatch.setattr(session_resolver, "CLAUDE_PATH", "/usr/local/bin/claude")
    monkeypatch.setattr(session_resolver, "resolve_agent_cfg",
                        lambda _sid: {"launch_alias": "agent_a", "cwd": "/tmp"})
    parent = register_session("agent_a", "parent")
    fork_meta = register_session("agent_a", "fork", parent_id=parent.id,
                                  resume_session_id="forked-claude-sid")
    sessions_meta[fork_meta.id] = fork_meta
    # prefer_fresh=True でも fork resume は維持される
    result = session_resolver.resolve_launch_alias(fork_meta.id, prefer_fresh=True)
    assert result == "/usr/local/bin/claude --resume forked-claude-sid"


def test_resolve_autoresume_fallback_prefer_fresh_returns_none(monkeypatch, isolated_state):
    """prefer_fresh=True なら fallback も None (= autoresume を踏まないから fallback も不要)。"""
    monkeypatch.setattr(session_resolver, "resolve_agent_cfg",
                        lambda _sid: {"launch_alias": "agent_a"})
    monkeypatch.setattr(session_resolver, "last_resumable_claude_sid",
                        lambda _sid: "old-claude-sid")
    # prefer_fresh=False は fallback alias を返す
    assert session_resolver.resolve_autoresume_fallback("ses_x") == "agent_a"
    # prefer_fresh=True は None
    assert session_resolver.resolve_autoresume_fallback("ses_x", prefer_fresh=True) is None
