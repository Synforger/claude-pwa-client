"""chat_routes.py の require_session 依存の unit test。

各 session 系 endpoint が共有する 404 ガードを 1 箇所に集約したもの。 存在すれば
session_id をそのまま返し、 無ければ HTTPException(404) を投げる。
"""
import asyncio

import pytest
from fastapi import HTTPException


def _setup_session(state, sid="ses_cfg"):
    from state import StreamState
    state.sessions_meta[sid] = object()
    state.stream_states[sid] = StreamState()
    return sid


def test_build_sessions_overview_reflects_busy(isolated_state):
    """全session overview payload が各 session の busy / pending_question を反映する (= 案B)。"""
    import chat_routes
    from state import StreamState
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
    assert ov["ses_a"] == {"busy": True, "pending_question": False}
    assert ov["ses_b"] == {"busy": False, "pending_question": True}


def test_require_session_passes_for_known_id(isolated_state):
    import chat_routes
    import state

    sid = "ses_known"
    # require_session は membership だけ見る (= 値は何でもよい)
    state.sessions_meta[sid] = object()
    assert chat_routes.require_session(sid) == sid


def test_require_session_raises_404_for_unknown(isolated_state):
    import chat_routes

    with pytest.raises(HTTPException) as exc:
        chat_routes.require_session("ses_does_not_exist")
    assert exc.value.status_code == 404


def test_stop_session_marks_user_stopped_and_clears_busy(isolated_state):
    """POST /sessions/{sid}/stop が user_stopped=True を立て busy を False に強制する。"""
    import chat_routes
    state = isolated_state
    sid = _setup_session(state)
    state.stream_states[sid].busy = True
    state.stream_states[sid].user_stopped = False

    result = asyncio.run(chat_routes.stop_session(sid, sid))
    assert result == {"ok": True}
    assert state.stream_states[sid].user_stopped is True
    assert state.stream_states[sid].busy is False


def test_stop_session_unknown_sid_returns_no_state(isolated_state):
    """state が無い sid に対しても 500 でなく ok=False を返す (= 多重押下耐性)。"""
    import chat_routes
    state = isolated_state
    # sessions_meta だけ生やして stream_states は作らない
    state.sessions_meta["ses_orphan"] = object()
    state.stream_states.pop("ses_orphan", None)

    result = asyncio.run(chat_routes.stop_session("ses_orphan", "ses_orphan"))
    assert result == {"ok": False, "reason": "no_state"}


def test_is_session_viewed_via_views_by_conn(isolated_state):
    """views_by_conn に sid を持つ接続があれば is_session_viewed が True を返す。"""
    from state import is_session_viewed, views_by_conn
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
