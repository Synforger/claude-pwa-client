"""chat_routes.py の require_session 依存の unit test。

各 session 系 endpoint が共有する 404 ガードを 1 箇所に集約したもの。 存在すれば
session_id をそのまま返し、 無ければ HTTPException(404) を投げる。
"""
import asyncio

import pytest
from fastapi import HTTPException


def _setup_session(state, sid="ses_cfg"):
    from backend.state import StreamState
    state.sessions_meta[sid] = object()
    state.stream_states[sid] = StreamState()
    return sid


def test_build_sessions_overview_reflects_busy(isolated_state):
    """全session overview payload が各 session の busy / pending_question を反映する (= 案B)。"""
    import backend.routes.chat as chat_routes
    from backend.state import StreamState
    state = isolated_state
    state.sessions_meta.clear()
    state.stream_states.clear()
    state.agent_status.clear()
    # busy=True の session と busy=False の session
    state.sessions_meta["ses_a"] = object()
    state.sessions_meta["ses_b"] = object()
    state.stream_states["ses_a"] = StreamState(busy=True)
    state.stream_states["ses_b"] = StreamState(busy=False)
    state.agent_status["ses_a"] = {"pending_question": None}
    state.agent_status["ses_b"] = {"pending_question": {"questions": []}}

    ov = chat_routes._build_sessions_overview()
    assert ov["ses_a"] == {"busy": True, "pending_question": False, "last_seen_at": None}
    assert ov["ses_b"] == {"busy": False, "pending_question": True, "last_seen_at": None}


def test_require_session_passes_for_known_id(isolated_state):
    import backend.routes.chat as chat_routes
    from backend import state

    sid = "ses_known"
    # require_session は membership だけ見る (= 値は何でもよい)
    state.sessions_meta[sid] = object()
    assert chat_routes.require_session(sid) == sid


def test_require_session_raises_404_for_unknown(isolated_state):
    import backend.routes.chat as chat_routes

    with pytest.raises(HTTPException) as exc:
        chat_routes.require_session("ses_does_not_exist")
    assert exc.value.status_code == 404


def test_mark_user_stopped_sets_flag_and_clears_busy(isolated_state):
    """/views/ws の stop メッセージで呼ばれる _mark_user_stopped が user_stopped=True を
    立て busy を False に強制する。"""
    import backend.routes.chat as chat_routes
    state = isolated_state
    sid = _setup_session(state)
    state.stream_states[sid].busy = True
    state.stream_states[sid].user_stopped = False

    assert chat_routes._mark_user_stopped(sid) is True
    assert state.stream_states[sid].user_stopped is True
    assert state.stream_states[sid].busy is False


def test_mark_user_stopped_returns_false_for_unknown_sid(isolated_state):
    """state が無い sid は False を返すだけで例外を出さない (= 多重 stop 耐性)。"""
    import backend.routes.chat as chat_routes
    state = isolated_state
    state.stream_states.pop("ses_orphan", None)
    assert chat_routes._mark_user_stopped("ses_orphan") is False


def test_is_session_viewed_via_views_by_conn(isolated_state):
    """views_by_conn に sid を持つ接続があれば is_session_viewed が True を返す。"""
    from backend.state import is_session_viewed, views_by_conn
    views_by_conn.clear()
    assert is_session_viewed("ses_x") is False
    views_by_conn["conn-uuid-1"] = "ses_x"
    try:
        assert is_session_viewed("ses_x") is True
        assert is_session_viewed("ses_other") is False
        # 別接続が消えれば false に戻る (= 切断で自動失効)
        del views_by_conn["conn-uuid-1"]
        assert is_session_viewed("ses_x") is False
    finally:
        views_by_conn.clear()


# --- backend-F-28 / crosscut-F-04: 3 分割後の互換 ---
def test_chat_router_includes_all_three_subrouters(isolated_state):
    """旧 chat.router 経由で list_sessions / status SSE / list_agents が全部到達できる
    (= 3 分割後も main.py の include は単一でよい互換)。

    fastapi 0.138+ では `include_router` の結果が `_IncludedRouter` wrapper になり
    `path` を直接持たないため、 1 段下の sub-router まで再帰して paths を集める
    (= 2026-06-29 fastapi 0.135 → 0.138 bump 時の test 互換修正)。
    """
    import backend.routes.chat as chat_routes
    paths: set[str] = set()
    for r in chat_routes.router.routes:
        path = getattr(r, "path", None)
        if path:
            paths.add(path)
        # fastapi 0.138+ では include_router の結果が `_IncludedRouter` wrapper、
        # 元の APIRouter を `.original_router` で公開する。 routes はそっち経由で展開。
        original = getattr(r, "original_router", None)
        sub_routes = getattr(original, "routes", None) if original is not None else None
        if sub_routes:
            for sub in sub_routes:
                sp = getattr(sub, "path", None)
                if sp:
                    paths.add(sp)
    assert "/sessions" in paths  # sessions.py
    assert "/sessions/status/stream" in paths  # overview.py
    assert "/agents" in paths  # accounts.py
    assert "/accounts" in paths


# --- backend-F-44: demote_fork_to_normal helper ---
def test_demote_fork_to_normal_clears_resume_id_and_gcs_jsonl(tmp_path, monkeypatch, isolated_state):
    """fork タブの resume_session_id を落として fork jsonl も unlink (= F-44 helper)。"""
    import backend.jsonl.watcher as jsonl_watcher
    state = isolated_state
    monkeypatch.setattr(state, "save_sessions_meta", lambda: None)
    monkeypatch.setattr(jsonl_watcher, "_cwd_to_project_dir", lambda cwd, account_id=None: tmp_path)
    from backend.config import AGENTS
    aid = next(iter(AGENTS))
    parent = state.register_session(aid, title="P")
    fork = state.register_session(
        aid, title="P fork", parent_id=parent.id, resume_session_id="fake-claude-uuid",
    )
    fork_jsonl = tmp_path / "fake-claude-uuid.jsonl"
    fork_jsonl.write_text("{}\n", encoding="utf-8")
    out = state.demote_fork_to_normal(fork.id)
    assert out == "fake-claude-uuid"
    assert state.sessions_meta[fork.id].resume_session_id is None
    assert not fork_jsonl.exists()


def test_demote_fork_to_normal_noop_for_regular_tab(monkeypatch, isolated_state):
    """通常タブ (= resume_session_id 無し) には何もしない (= None を返す)。"""
    state = isolated_state
    monkeypatch.setattr(state, "save_sessions_meta", lambda: None)
    from backend.config import AGENTS
    aid = next(iter(AGENTS))
    normal = state.register_session(aid, title="N")
    assert state.demote_fork_to_normal(normal.id) is None
    assert state.sessions_meta[normal.id].resume_session_id is None


def test_demote_fork_to_normal_unknown_sid_returns_none(isolated_state):
    """unknown sid は静かに None。 例外を出さない (= restart の defensive 経路保護)。"""
    state = isolated_state
    assert state.demote_fork_to_normal("ses_nonexistent") is None


# --- backend-F-27 / crosscut-F-27: jsonl resolver ---
def test_resolve_jsonl_live_delegates_to_runner(monkeypatch, isolated_state):
    """prefer="live" は pty_runner.jsonl_path_for_session に丸投げ。"""
    from pathlib import Path
    import backend.terminal.runner as pty_runner
    from backend.jsonl import resolver
    expected = Path("/tmp/fake.jsonl")
    monkeypatch.setattr(pty_runner, "jsonl_path_for_session", lambda sid: expected)
    assert resolver.resolve_jsonl("ses_x", prefer="live") is expected


def test_resolve_jsonl_project_dir_uses_account_aware_lookup(tmp_path, monkeypatch, isolated_state):
    """prefer="project_dir" は SessionDef.account_id を _cwd_to_project_dir に渡す。"""
    import backend.jsonl.watcher as jsonl_watcher
    from backend.jsonl import resolver
    from backend.config import AGENTS
    state = isolated_state
    monkeypatch.setattr(state, "save_sessions_meta", lambda: None)
    aid = next(iter(AGENTS))
    sess = state.register_session(aid, title="S", account_id="personal")
    captured: dict = {}
    def _fake(cwd, account_id=None):
        captured["cwd"] = cwd
        captured["account_id"] = account_id
        return tmp_path
    monkeypatch.setattr(jsonl_watcher, "_cwd_to_project_dir", _fake)
    out = resolver.resolve_jsonl(sess.id, prefer="project_dir")
    assert out == tmp_path
    assert captured["account_id"] == "personal"


def test_resolve_jsonl_scan_returns_mtime_desc(tmp_path, monkeypatch, isolated_state):
    """prefer="scan" は project_dir 配下の jsonl を mtime desc で返す。"""
    import backend.jsonl.watcher as jsonl_watcher
    from backend.jsonl import resolver
    from backend.config import AGENTS
    state = isolated_state
    monkeypatch.setattr(state, "save_sessions_meta", lambda: None)
    aid = next(iter(AGENTS))
    sess = state.register_session(aid, title="S")
    monkeypatch.setattr(jsonl_watcher, "_cwd_to_project_dir", lambda cwd, account_id=None: tmp_path)
    import os, time as _t
    a = tmp_path / "a.jsonl"; a.write_text("a"); os.utime(a, (1, 1))
    b = tmp_path / "b.jsonl"; b.write_text("b"); os.utime(b, (2, 2))
    c = tmp_path / "c.jsonl"; c.write_text("c"); os.utime(c, (3, 3))
    out = resolver.resolve_jsonl(sess.id, prefer="scan")
    assert [p.name for p in out] == ["c.jsonl", "b.jsonl", "a.jsonl"]


def test_resolve_jsonl_scan_empty_when_project_dir_missing(monkeypatch, isolated_state):
    """project_dir 解決不能 (= cwd 無設定 + live binding 無し) なら空 list。"""
    import backend.terminal.runner as pty_runner
    from backend.jsonl import resolver
    from backend.config import AGENTS
    state = isolated_state
    monkeypatch.setattr(state, "save_sessions_meta", lambda: None)
    aid = next(iter(AGENTS))
    sess = state.register_session(aid, title="S")
    monkeypatch.setattr(pty_runner, "jsonl_path_for_session", lambda sid: None)
    # AGENTS[aid].cwd は test conftest で home dir (= 実在) が入ってるので
    # 実在 dir に何も jsonl が無いケース = []
    import backend.jsonl.watcher as jsonl_watcher
    monkeypatch.setattr(jsonl_watcher, "_cwd_to_project_dir",
                        lambda cwd, account_id=None: __import__("pathlib").Path("/no/such/dir/ever"))
    out = resolver.resolve_jsonl(sess.id, prefer="scan")
    assert out == []


def test_resolve_jsonl_unknown_prefer_raises(isolated_state):
    """typo 検出のため未知 prefer は ValueError。"""
    from backend.jsonl import resolver
    import pytest as _pytest
    with _pytest.raises(ValueError):
        resolver.resolve_jsonl("ses_x", prefer="bogus")  # type: ignore[arg-type]


# --- backend-F-09 / F-10: SSE diff + keep-alive comment ---
def test_build_sessions_overview_includes_last_seen_at(isolated_state):
    """last_seen_at が overview snapshot に乗る (= 既存仕様の構造的回帰防止)。"""
    import backend.routes.chat as chat_routes
    from backend.state import StreamState
    state = isolated_state
    state.sessions_meta.clear(); state.stream_states.clear(); state.agent_status.clear()
    state.session_last_seen_at.clear()
    state.sessions_meta["ses_a"] = object()
    state.stream_states["ses_a"] = StreamState(busy=False)
    state.agent_status["ses_a"] = {"pending_question": None}
    state.session_last_seen_at["ses_a"] = 1234.5
    ov = chat_routes._build_sessions_overview()
    assert ov["ses_a"]["last_seen_at"] == 1234.5


def test_rate_limits_tail_memoize_caches_within_ttl(monkeypatch, isolated_state):
    """F-56: 1 秒以内の 2 回目は file I/O を呼ばず cache を返す。"""
    import backend.routes.overview as overview_mod
    calls = {"n": 0}
    def _fake_tail():
        calls["n"] += 1
        return [{"account_id": "personal", "five_hour_pct": 10}]
    monkeypatch.setattr(overview_mod, "read_all_rate_limits_tail", _fake_tail)
    # cache を invalidate
    overview_mod._RATE_TAIL_CACHE = (0.0, [])
    a = overview_mod._read_rate_limits_tail_cached()
    b = overview_mod._read_rate_limits_tail_cached()
    assert a == b
    assert calls["n"] == 1  # 1 秒以内なら 1 回だけ I/O
