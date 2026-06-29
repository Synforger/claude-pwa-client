"""`/jsonl/stream/{sid}` 旧 endpoint と新 `/jsonl/stream/all` の integration test (= F-02 / F-15)。

前提要件: 既存 frontend (= 旧 endpoint 利用) は無変更で動くこと。 本 test では
1. 旧 per-sid SSE: file 内の過去 message を replay → broadcaster publish した event を受信
2. 新 /all SSE: 複数 sid に publish したものが 1 接続で受信できる + event に sid field
の 2 経路を担保する。
"""
import asyncio
import json

import backend.jsonl.routes as jr
import backend.state as state_mod


def _run(coro):
    """asyncio.run は default loop を閉じて後続 test を壊すので new loop を都度作る。"""
    loop = asyncio.new_event_loop()
    try:
        asyncio.set_event_loop(loop)
        return loop.run_until_complete(coro)
    finally:
        loop.close()
        asyncio.set_event_loop(asyncio.new_event_loop())


def _make_sid(state, sid: str, agent_id: str = "a"):
    state.stream_states[sid] = state_mod.StreamState(agent_id=agent_id)
    state.agent_status[sid] = state_mod._make_agent_status(agent_id)


def test_per_sid_sse_replays_from_file_and_subscribes(isolated_state, monkeypatch, tmp_path):
    """旧 per-sid SSE 経路: file replay (= ?from=offset) → broadcaster publish event を Queue
    経由で受ける。 mutator は呼ばない (= replay は pure)。"""
    state = isolated_state
    sid = "ses_compat_a"
    _make_sid(state, sid)
    # fake JSONL file: 1 行の素ユーザ発話
    jpath = tmp_path / f"{sid}.jsonl"
    jpath.write_text(json.dumps({"type": "user", "uuid": "u1",
                                  "message": {"content": "hello"}}) + "\n")
    monkeypatch.setattr(jr, "_latest_jsonl", lambda _sid: jpath)
    # ensure_pty_session_for は副作用無しでスキップ
    async def _noop(_sid, **_kwargs):
        return None
    monkeypatch.setattr("backend.terminal.routes.ensure_pty_session_for", _noop)

    async def run():
        gen = jr._jsonl_sse(sid, start_pos=0)
        # 1) replay phase: user_message frame
        frame = await asyncio.wait_for(gen.__anext__(), timeout=1.0)
        assert "data: " in frame
        payload = json.loads(frame.split("data: ", 1)[1].strip())
        assert payload.get("type") == "user_message"
        # 2) live phase: broadcaster publish した event が Queue 経由で届く
        live_event = {"type": "assistant", "sid": sid, "uuid": "live1",
                      "message": {"content": [{"type": "text", "text": "live"}]}}
        # publish は背後の subscribe を経由するので、 wait_for で gen.__anext__ を開始してから
        # publish する
        async def publisher():
            await asyncio.sleep(0.01)
            state_mod.jsonl_event_broadcaster.publish(sid, live_event)
        pub_task = asyncio.create_task(publisher())
        frame2 = await asyncio.wait_for(gen.__anext__(), timeout=1.0)
        await pub_task
        # keep-alive か live event のどちらか。 timeout=_IDLE_MAX_INTERVAL(2s) より速いので live のはず
        if frame2.startswith(":"):
            # keep-alive を踏んだら次を待つ
            frame2 = await asyncio.wait_for(gen.__anext__(), timeout=2.5)
        payload2 = json.loads(frame2.split("data: ", 1)[1].strip())
        assert payload2.get("uuid") == "live1"
        # cleanup
        await gen.aclose()

    _run(run())


def test_all_sse_fans_out_multiple_sids(isolated_state, monkeypatch, tmp_path):
    """新 /jsonl/stream/all 経路: 2 sid に publish したものが 1 接続で受信できる。 event に
    sid field が乗っていることを確認 (= frontend が振り分けに使う)。"""
    state = isolated_state
    sid_a = "ses_compat_x"
    sid_b = "ses_compat_y"
    _make_sid(state, sid_a)
    _make_sid(state, sid_b)
    # 空 file をそれぞれ作って _latest_jsonl 経路を満たす (= replay は空 = 即 live phase)
    for sid in (sid_a, sid_b):
        (tmp_path / f"{sid}.jsonl").write_text("")

    def _latest(sid):
        return tmp_path / f"{sid}.jsonl"
    monkeypatch.setattr(jr, "_latest_jsonl", _latest)

    async def _noop(_sid, **_kwargs):
        return None
    monkeypatch.setattr("backend.terminal.routes.ensure_pty_session_for", _noop)

    async def run():
        gen = jr._jsonl_sse_all({})
        async def publisher():
            await asyncio.sleep(0.02)
            state_mod.jsonl_event_broadcaster.publish(sid_a, {
                "type": "assistant", "sid": sid_a, "uuid": "ax",
                "message": {"content": [{"type": "text", "text": "a"}]},
            })
            state_mod.jsonl_event_broadcaster.publish(sid_b, {
                "type": "assistant", "sid": sid_b, "uuid": "by",
                "message": {"content": [{"type": "text", "text": "b"}]},
            })
        pub_task = asyncio.create_task(publisher())
        seen_sids = set()
        # 最大 5 frame まで待つ (= keep-alive を踏むことがあるので余裕を持つ)
        for _ in range(5):
            frame = await asyncio.wait_for(gen.__anext__(), timeout=2.5)
            if frame.startswith(":"):
                continue
            payload = json.loads(frame.split("data: ", 1)[1].strip())
            if payload.get("type") == "assistant":
                seen_sids.add(payload.get("sid"))
            if seen_sids == {sid_a, sid_b}:
                break
        await pub_task
        await gen.aclose()
        assert seen_sids == {sid_a, sid_b}

    _run(run())
