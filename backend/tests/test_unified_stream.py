"""統合 stream (= /stream/unified + control POST) の unit / integration test。

担保する不変条件 (= 2026-07-14 電力効率工事の核):
1. jsonl channel は購読 sid のみ流れる (= 未購読 sid の event は wire に乗らない)
2. replay は per-line 実 byte pos を frame に載せる (= client offset が前進できる)
3. warmup (= ensure_pty) は購読 sid のみ (= 全 sid sweep の廃止)
4. control op: 購読差替 (= 追加 sid の差分 replay) / view 申告 / stop / 404
5. 切断 cleanup (= conn 登録 + views_by_conn が消える)
"""
import asyncio
import json

import pytest
from fastapi import HTTPException

import backend.routes.unified_stream as us
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
    # 本物の SessionDef (= _build_all_status が account_id を読む)
    state.sessions_meta[sid] = state_mod.SessionDef(
        id=sid, agent_id=agent_id, title=sid, created_at=0)


def _parse(frame: str) -> dict:
    assert frame.startswith("data: ")
    return json.loads(frame[len("data: "):].strip())


@pytest.fixture
def unified_env(isolated_state, monkeypatch, tmp_path):
    """2 sid (a=購読 / b=非購読) + fake JSONL + PTY spy を組んだ共通環境。"""
    state = isolated_state
    sid_a, sid_b = "ses_uni_a", "ses_uni_b"
    _make_sid(state, sid_a)
    _make_sid(state, sid_b)
    for sid, text in ((sid_a, "hello-a"), (sid_b, "hello-b")):
        (tmp_path / f"{sid}.jsonl").write_text(
            json.dumps({"type": "user", "uuid": f"u-{sid}", "message": {"content": text}}) + "\n")
    monkeypatch.setattr(
        "backend.jsonl.routes.jsonl_path_for_session", lambda s: tmp_path / f"{s}.jsonl")
    ensured: list[str] = []

    async def _spy(sid, **_kwargs):
        ensured.append(sid)
    monkeypatch.setattr("backend.terminal.routes.ensure_pty_session_for", _spy)
    # status/overview builder は本物 (= sessions_meta の 2 sid 分を吐く)
    us._conns.clear()
    yield state, sid_a, sid_b, ensured
    us._conns.clear()


def _mk_conn(sid_subs: dict[str, int | None]) -> us.UnifiedConn:
    conn = us.UnifiedConn(conn_id="c1")
    conn.jsonl_sids = set(sid_subs)
    conn.initial_replay = [
        f for sid in sorted(sid_subs) for f in us._replay_frames(sid, sid_subs[sid])
    ]
    return conn


async def _read_until(gen, pred, limit=30, timeout=2.5):
    """generator から pred を満たす frame まで読み進める (= 満たしたら (frame, parsed))。"""
    for _ in range(limit):
        frame = await asyncio.wait_for(gen.__anext__(), timeout=timeout)
        payload = _parse(frame)
        if pred(payload):
            return frame, payload
    raise AssertionError("frame not found within limit")


def test_connect_replays_only_subscribed_sid_with_pos(unified_env):
    state, sid_a, sid_b, ensured = unified_env

    async def run():
        conn = _mk_conn({sid_a: 0})
        gen = us._unified_gen(conn, initial_view=sid_a)
        seen = []
        # hello → replay(jsonl) → prompt_state → status → overview まで読む
        for _ in range(6):
            payload = _parse(await asyncio.wait_for(gen.__anext__(), timeout=2.5))
            seen.append(payload)
            if payload.get("ch") == "overview":
                break
        await gen.aclose()
        chs = [p["ch"] for p in seen]
        assert chs[0] == "sys" and seen[0]["type"] == "hello"
        assert "status" in chs and "overview" in chs
        # replay は sid_a のみ + per-line 実 pos
        jsonl_frames = [p for p in seen if p["ch"] == "jsonl" and p["ev"].get("type") == "user_message"]
        assert len(jsonl_frames) == 1
        assert jsonl_frames[0]["ev"]["sid"] == sid_a
        assert isinstance(jsonl_frames[0]["pos"], int) and jsonl_frames[0]["pos"] > 0
        # sid_b の replay は 1 frame も無い
        assert all(p["ev"].get("sid") != sid_b for p in seen if p["ch"] == "jsonl")
        # warmup は購読 sid のみ
        assert ensured == [sid_a]
        # view 申告が登録され、 切断で消える
        assert state_mod.views_by_conn.get("c1") is None  # aclose 済み

    _run(run())


def test_live_filter_only_subscribed_sid(unified_env):
    state, sid_a, sid_b, ensured = unified_env

    async def run():
        conn = _mk_conn({sid_a: None})
        gen = us._unified_gen(conn, initial_view=None)
        await _read_until(gen, lambda p: p.get("ch") == "overview")

        async def publisher():
            await asyncio.sleep(0.02)
            state_mod.jsonl_event_broadcaster.publish(
                sid_b, {"type": "assistant", "sid": sid_b, "uuid": "nope",
                        "message": {"content": [{"type": "text", "text": "b"}]}}, 111)
            state_mod.jsonl_event_broadcaster.publish(
                sid_a, {"type": "assistant", "sid": sid_a, "uuid": "yes",
                        "message": {"content": [{"type": "text", "text": "a"}]}}, 222)
        pub = asyncio.create_task(publisher())
        _, payload = await _read_until(
            gen, lambda p: p.get("ch") == "jsonl" and p["ev"].get("type") == "assistant")
        await pub
        await gen.aclose()
        # sid_b (= 111 / nope) は届かず、 sid_a (= 222 / yes) だけが届く
        assert payload["ev"]["uuid"] == "yes"
        assert payload["pos"] == 222

    _run(run())


def test_control_jsonl_adds_subscription_with_replay(unified_env):
    state, sid_a, sid_b, ensured = unified_env

    async def run():
        conn = _mk_conn({sid_a: None})
        gen = us._unified_gen(conn, initial_view=None)
        await _read_until(gen, lambda p: p.get("ch") == "overview")
        assert ensured == [sid_a]

        # 購読差替: sid_b を追加 (= from 無し → 直近 N 行 replay)
        res = await us.stream_unified_control(
            "c1", {"op": "jsonl", "sids": [{"sid": sid_a}, {"sid": sid_b}]})
        assert res["ok"] is True and sorted(res["subscribed"]) == [sid_a, sid_b]
        assert conn.jsonl_sids == {sid_a, sid_b}
        assert ensured == [sid_a, sid_b]  # 追加分だけ warmup

        # 追加 sid の replay が同一接続に流れてくる
        _, payload = await _read_until(
            gen, lambda p: p.get("ch") == "jsonl" and p["ev"].get("sid") == sid_b
            and p["ev"].get("type") == "user_message")
        assert payload["ev"]["uuid"] == f"u-{sid_b}"

        # 差替で sid_a を外す → live event が届かない
        await us.stream_unified_control("c1", {"op": "jsonl", "sids": [{"sid": sid_b}]})
        assert conn.jsonl_sids == {sid_b}
        await gen.aclose()

    _run(run())


def test_control_view_and_stop_and_unknown(unified_env):
    state, sid_a, _sid_b, _ensured = unified_env

    async def run():
        conn = _mk_conn({})
        gen = us._unified_gen(conn, initial_view=None)
        await _read_until(gen, lambda p: p.get("ch") == "overview")

        # view 申告
        await us.stream_unified_control("c1", {"op": "view", "sid": sid_a})
        assert state_mod.views_by_conn["c1"] == sid_a
        await us.stream_unified_control("c1", {"op": "view", "sid": None})
        assert "c1" not in state_mod.views_by_conn

        # stop: busy を強制 false + user_stopped
        st = state_mod.stream_states[sid_a]
        st.busy = True
        res = await us.stream_unified_control("c1", {"op": "stop", "sid": sid_a})
        assert res["ok"] is True
        assert st.user_stopped is True and st.busy is False

        # 不明 op / 不明 conn
        with pytest.raises(HTTPException) as e1:
            await us.stream_unified_control("c1", {"op": "bogus"})
        assert e1.value.status_code == 422
        with pytest.raises(HTTPException) as e2:
            await us.stream_unified_control("nope", {"op": "view", "sid": sid_a})
        assert e2.value.status_code == 404
        await gen.aclose()

    _run(run())


def test_disconnect_cleans_registry_and_views(unified_env):
    state, sid_a, _sid_b, _ensured = unified_env

    async def run():
        conn = _mk_conn({sid_a: None})
        gen = us._unified_gen(conn, initial_view=sid_a)
        await _read_until(gen, lambda p: p.get("ch") == "overview")
        assert us._conns.get("c1") is conn
        assert state_mod.views_by_conn.get("c1") == sid_a
        await gen.aclose()
        assert "c1" not in us._conns
        assert "c1" not in state_mod.views_by_conn

    _run(run())


def test_keepalive_frame_when_idle(unified_env, monkeypatch):
    _state, sid_a, _sid_b, _ensured = unified_env
    monkeypatch.setattr(us, "KEEPALIVE_SEC", 0.05)

    async def run():
        conn = _mk_conn({sid_a: None})
        gen = us._unified_gen(conn, initial_view=None)
        await _read_until(gen, lambda p: p.get("ch") == "overview")
        _, payload = await _read_until(gen, lambda p: p.get("ch") == "sys" and p.get("_hb") == 1)
        assert payload["_hb"] == 1
        await gen.aclose()

    _run(run())
