"""state.py の pure 関数の unit test。 第一弾は _default_title のみ。"""
import state


def test_default_title_uses_display_name(monkeypatch):
    # 意図: AGENTS[id].display_name があればそれを base にして "<base>-<n>"
    monkeypatch.setitem(state.AGENTS, "_test_agent", {"display_name": "Fake"})
    assert state._default_title("_test_agent", 3) == "Fake-3"


def test_default_title_falls_back_to_upper(monkeypatch):
    # 意図: display_name 未定義は agent_id.upper() を base にする
    monkeypatch.setitem(state.AGENTS, "_test_tiny", {})
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
