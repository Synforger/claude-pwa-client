"""state.py の pure 関数 + SessionState 集約 + NotifyMode Enum の unit test。"""
import asyncio

from backend import state


def test_default_title_uses_display_name(monkeypatch):
    # 意図: AGENTS[id].display_name があればそれを base にして "<base>-<n>"
    monkeypatch.setattr(state, "_agents",
                        lambda: {"_test_agent": {"display_name": "Fake"}})
    assert state._default_title("_test_agent", 3) == "Fake-3"


def test_default_title_falls_back_to_upper(monkeypatch):
    # 意図: display_name 未定義は agent_id.upper() を base にする
    monkeypatch.setattr(state, "_agents", lambda: {"_test_tiny": {}})
    assert state._default_title("_test_tiny", 1) == "_TEST_TINY-1"


def test_default_title_unknown_agent_id():
    # 意図: AGENTS に無い id でも upper fallback (= migration 中の保険)
    assert state._default_title("_ghost_agent", 7) == "_GHOST_AGENT-7"


def test_session_def_notify_mode_default_and_serialization():
    sd = state.SessionDef(id="s1", agent_id="a", title="t", created_at=0)
    assert sd.notify_mode == "both"  # 既定
    assert sd.to_dict()["notify_mode"] == "both"


def test_set_notify_mode(monkeypatch):
    monkeypatch.setitem(state.sessions_meta, "s_notif",
                        state.SessionDef(id="s_notif", agent_id="a", title="t", created_at=0))
    monkeypatch.setattr(state, "save_sessions_meta", lambda: None)
    # 有効値は受理して反映
    assert state.set_notify_mode("s_notif", "banner") is True
    assert state.sessions_meta["s_notif"].notify_mode == "banner"
    assert state.set_notify_mode("s_notif", "off") is True
    assert state.sessions_meta["s_notif"].notify_mode == "off"
    # 不正値 / 未知 session は False、 既存値は保たれる
    assert state.set_notify_mode("s_notif", "soundonly") is False
    assert state.sessions_meta["s_notif"].notify_mode == "off"
    assert state.set_notify_mode("nope", "both") is False


# ============================================================================
# AgentStatus dataclass (= backend-F-16 / F-37 / F-38)
# ============================================================================

def test_agent_status_for_agent_picks_up_model(monkeypatch):
    monkeypatch.setattr(state, "_agents", lambda: {"a1": {"model": "Opus"}})
    s = state.AgentStatus.for_agent("a1")
    assert s.model == "Opus"
    # default は dataclass 1 箇所で定義されるので、 後段の to_dict() でも同値
    assert s.to_dict()["plan_mode"] is False
    assert s.to_dict()["pr_links"] == []


def test_make_agent_status_returns_dict_with_all_keys(monkeypatch):
    monkeypatch.setattr(state, "_agents", lambda: {"a1": {"model": "Opus"}})
    d = state._make_agent_status("a1")
    # 旧 consumer 互換: plain dict が返って、 既知の key 全部が入っている
    expected_keys = {
        "ctx_pct", "ctx_window", "model", "plan_mode", "current_tool",
        "todos", "subagent", "pending_plan", "pending_question", "mode",
        "permission_mode", "budget_used", "budget_total", "budget_remaining",
        "pr_links", "tasks",
    }
    assert set(d.keys()) == expected_keys
    assert d["model"] == "Opus"


def test_agent_status_to_dict_shares_list_reference():
    # list / dict field は to_dict() で同 object 共有 (= 旧 dict factory と同挙動)
    s = state.AgentStatus()
    d = s.to_dict()
    d["pr_links"].append({"prRepository": "r", "prNumber": 1})
    # dataclass 側からも見える
    assert s.pr_links == [{"prRepository": "r", "prNumber": 1}]


# ============================================================================
# NotifyMode Enum (= crosscut-F-20)
# ============================================================================

def test_notify_mode_enum_values_match_legacy_tuple():
    # 旧 wire format の "both" / "banner" / "off" を Enum value で保持し、
    # 旧 NOTIFY_MODES tuple は Enum value から導出する (= 後方互換)
    assert state.NOTIFY_MODES == ("both", "banner", "off")
    assert state.NotifyMode.BOTH.value == "both"
    assert state.NotifyMode.BANNER.value == "banner"
    assert state.NotifyMode.OFF.value == "off"


def test_set_notify_mode_accepts_enum(monkeypatch):
    monkeypatch.setitem(state.sessions_meta, "s_enum",
                        state.SessionDef(id="s_enum", agent_id="a", title="t", created_at=0))
    monkeypatch.setattr(state, "save_sessions_meta", lambda: None)
    # Enum を渡しても string に正規化して永続化する
    assert state.set_notify_mode("s_enum", state.NotifyMode.BANNER) is True
    assert state.sessions_meta["s_enum"].notify_mode == "banner"


# ============================================================================
# SessionState (= backend-F-07): lock + dict 共有 view
# ============================================================================

def test_register_session_creates_session_state(monkeypatch, tmp_path):
    monkeypatch.setattr(state, "_agents", lambda: {"a1": {"model": "Opus"}})
    monkeypatch.setattr(state, "SESSION_META_PATH", tmp_path / "meta.json")
    # 既存 dict と SessionState の参照共有確認のため、 既存 sid を全部退避
    backup = (
        dict(state.sessions_meta),
        dict(state.stream_states),
        dict(state.agent_status),
        dict(state.session_states),
    )
    try:
        state.sessions_meta.clear()
        state.stream_states.clear()
        state.agent_status.clear()
        state.session_states.clear()
        meta = state.register_session("a1", title="X")
        sid = meta.id
        s = state.get_session(sid)
        assert s is not None
        assert s.meta is state.sessions_meta[sid]            # 同 object
        assert s.stream is state.stream_states[sid]          # 同 object
        assert s.status is state.agent_status[sid]           # 同 object
        # SessionState.status を mutate すれば agent_status[sid] からも見える
        s.status["model"] = "Sonnet"
        assert state.agent_status[sid]["model"] == "Sonnet"
        # tmp_files も同 list 参照
        assert s.tmp_files is state.session_tmp_files[sid]
    finally:
        state.sessions_meta.clear(); state.sessions_meta.update(backup[0])
        state.stream_states.clear(); state.stream_states.update(backup[1])
        state.agent_status.clear(); state.agent_status.update(backup[2])
        state.session_states.clear(); state.session_states.update(backup[3])


def test_unregister_session_removes_session_state(monkeypatch, tmp_path):
    monkeypatch.setattr(state, "_agents", lambda: {"a1": {"model": "Opus"}})
    monkeypatch.setattr(state, "SESSION_META_PATH", tmp_path / "meta.json")
    backup = (
        dict(state.sessions_meta), dict(state.stream_states),
        dict(state.agent_status), dict(state.session_states),
    )
    try:
        state.sessions_meta.clear()
        state.stream_states.clear()
        state.agent_status.clear()
        state.session_states.clear()
        meta = state.register_session("a1")
        sid = meta.id
        assert state.get_session(sid) is not None
        assert state.unregister_session(sid) is True
        assert state.get_session(sid) is None
        assert sid not in state.session_states
    finally:
        state.sessions_meta.clear(); state.sessions_meta.update(backup[0])
        state.stream_states.clear(); state.stream_states.update(backup[1])
        state.agent_status.clear(); state.agent_status.update(backup[2])
        state.session_states.clear(); state.session_states.update(backup[3])


def test_session_state_lock_serializes_modifications(monkeypatch, tmp_path):
    """SessionState.lock 配下なら read-modify-write が atomic。 旧設計の
    `agent_status[sid]["pr_links"].append` race を消す入口を担保する。

    pytest-asyncio が未導入なので、 asyncio.run で event loop を内側に閉じて
    同期 test として実装する (= dependency 追加を避ける)。"""
    monkeypatch.setattr(state, "_agents", lambda: {"a1": {"model": "Opus"}})
    monkeypatch.setattr(state, "SESSION_META_PATH", tmp_path / "meta.json")
    backup = (
        dict(state.sessions_meta), dict(state.stream_states),
        dict(state.agent_status), dict(state.session_states),
    )
    try:
        state.sessions_meta.clear()
        state.stream_states.clear()
        state.agent_status.clear()
        state.session_states.clear()
        meta = state.register_session("a1")
        sid = meta.id

        async def runner():
            s = state.get_session(sid)

            async def bump(n):
                async with s.lock:
                    cur = list(s.status["pr_links"])
                    # わざと await を挟んで context switch を強制する (= race を露わにする)
                    await asyncio.sleep(0)
                    cur.append(n)
                    s.status["pr_links"] = cur

            await asyncio.gather(*(bump(i) for i in range(50)))
            return list(s.status["pr_links"])

        result = asyncio.run(runner())
        assert sorted(result) == list(range(50))
    finally:
        state.sessions_meta.clear(); state.sessions_meta.update(backup[0])
        state.stream_states.clear(); state.stream_states.update(backup[1])
        state.agent_status.clear(); state.agent_status.update(backup[2])
        state.session_states.clear(); state.session_states.update(backup[3])


def test_get_or_create_lock_for_unknown_sid_returns_lock():
    lk = state.get_or_create_lock("nope")
    assert isinstance(lk, asyncio.Lock)
