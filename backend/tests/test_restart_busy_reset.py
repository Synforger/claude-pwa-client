"""restart_session は推論中 (busy) の状態を落とす (= 「推論中に終了 → 青丸残留」 の根治)。

青丸 = overview の busy = stream_states[sid].busy OR pane_working (user_stopped 時のみ強制
False)。 restart は user_stopped=False に戻す一方で busy / pane_working / queued_sends を
落とさないと、 終了がマスクを剥がして残留 busy を青丸として露出させる。 停止 (stopMessage)
は同期で busy を落とすので、 終了もこれに対称化する。 本 test で回帰固定する。
"""
from __future__ import annotations

import asyncio


def _run(coro):
    # asyncio.run で毎回新規ループを立てる (= 先行 test がループを閉じた後でも安定、
    # get_event_loop() の「現在のループ無し」 RuntimeError を踏まない)。
    return asyncio.run(coro)


def _stub_restart_io(monkeypatch):
    """restart の kill / spawn / tail-reset / history I/O を test 用に無害化する。"""
    import backend.routes.sessions as sessions_routes
    import backend.jsonl.routes as jsonl_routes
    import backend.terminal.routes as pty_routes

    monkeypatch.setattr(sessions_routes, "kill_tmux_session", lambda sid: None)
    monkeypatch.setattr(sessions_routes.jsonl_watcher, "get_jsonl_for", lambda sid: None)
    monkeypatch.setattr(sessions_routes.jsonl_watcher, "unregister", lambda sid: None)
    monkeypatch.setattr(jsonl_routes, "request_sid_tail_reset", lambda sid: None)

    async def _noop_spawn(_sid, **_kwargs):
        return None

    monkeypatch.setattr(pty_routes, "ensure_pty_session_for", _noop_spawn)
    return sessions_routes


def test_restart_clears_busy_state(monkeypatch, isolated_state):
    """推論中 (busy / spinner / queue) の session を restart したら busy 系が全て落ちる。"""
    state = isolated_state
    monkeypatch.setattr(state, "save_sessions_meta", lambda: None)
    sessions_routes = _stub_restart_io(monkeypatch)

    # agent_id は register_session が検査する _agents() から実行時に引く (= conftest が
    # config.AGENTS を差し替えるので module 冒頭 import は古くなる)。
    aid = next(iter(state._agents()))
    sess_def = state.register_session(aid, title="Chat")
    sid = sess_def.id

    # 推論中を再現: busy / TUI スピナー / queue 積み残しが立った状態。
    st = state.stream_states[sid]
    st.busy = True
    st.pane_working = True
    st.queued_sends = 2

    out = _run(sessions_routes.restart_session(sid))
    assert out["ok"] is True

    # 対称化: 終了は停止と同じく busy 系を落とす (= 青丸が残らない)。
    st_after = state.stream_states[sid]
    assert st_after.busy is False
    assert st_after.pane_working is False
    assert st_after.queued_sends == 0
