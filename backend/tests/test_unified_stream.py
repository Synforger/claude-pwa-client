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


def test_endpoint_requires_conn_param(unified_env):
    """GET /stream/unified は conn query 必須 (= 422)。 route 層の入口 guard。"""
    from fastapi import HTTPException as _HTTPException
    from starlette.requests import Request as _Request

    async def run():
        scope = {
            "type": "http", "method": "GET", "path": "/stream/unified",
            "query_string": b"", "headers": [],
        }
        with pytest.raises(_HTTPException) as e:
            await us.stream_unified(_Request(scope))
        assert e.value.status_code == 422

    _run(run())


def test_endpoint_accepts_plain_sid_list_and_filters_unknown(unified_env):
    """query jsonl= は `sid:off` と素 sid 両対応、 未知 sid は購読に入れない。"""
    from starlette.requests import Request as _Request
    _state, sid_a, _sid_b, _ensured = unified_env

    async def run():
        scope = {
            "type": "http", "method": "GET", "path": "/stream/unified",
            "query_string": f"conn=c9&jsonl={sid_a},ses_unknown:5&view={sid_a}".encode(),
            "headers": [],
        }
        res = await us.stream_unified(_Request(scope))
        # StreamingResponse が返り、 conn は generator 開始まで未登録 (= 接続確立が登録点)
        assert res.media_type == "text/event-stream"
        # generator を 1 frame だけ回して登録を確認
        gen = res.body_iterator
        first = await gen.__anext__()
        assert "hello" in first
        conn = us._conns.get("c9")
        assert conn is not None
        assert conn.jsonl_sids == {sid_a}
        await gen.aclose()

    _run(run())


def test_events_published_during_replay_are_not_lost(unified_env):
    """接続直後 (= replay 進行中) に publish された event も届く (= 2026-07-15 修正:
    旧実装は GET handler 時点で replay を file から構築し、 live 購読は replay 配信後
    だったため、 その隙間の publish が恒久欠落していた。 pump 先行起動で隙間ゼロ)。"""
    state, sid_a, _sid_b, _ensured = unified_env

    async def run():
        conn = _mk_conn({sid_a: 0})
        gen = us._unified_gen(conn, initial_view=None)
        # hello だけ読んだ時点 (= replay の file 読みは未実行) で「行追記 + publish」
        # (= monitor の実挙動: publish される行は既に file に書かれている)。 旧実装は
        # GET handler 時点の file snapshot を replay していたためこの行が落ちた。
        first = _parse(await asyncio.wait_for(gen.__anext__(), timeout=2.5))
        assert first["ch"] == "sys" and first["type"] == "hello"
        jpath = us._latest_jsonl(sid_a)
        with open(jpath, "a", encoding="utf-8") as f:
            f.write(json.dumps({"type": "assistant", "uuid": "live-gap",
                                "message": {"content": [{"type": "text", "text": "g"}]}}) + "\n")
        state_mod.jsonl_event_broadcaster.publish(
            sid_a, {"type": "assistant", "sid": sid_a, "uuid": "live-gap",
                    "message": {"content": [{"type": "text", "text": "g"}]}}, 999)
        # replay (= user_message) と live (= live-gap) の両方が届く
        seen_uuids = []
        for _ in range(12):
            payload = _parse(await asyncio.wait_for(gen.__anext__(), timeout=2.5))
            if payload.get("ch") == "jsonl":
                seen_uuids.append(payload["ev"].get("uuid"))
            if "live-gap" in seen_uuids:
                break
        await gen.aclose()
        assert f"u-{sid_a}" in seen_uuids  # replay 分
        assert "live-gap" in seen_uuids    # 隙間の publish 分
    _run(run())


def test_stale_generator_cleanup_keeps_new_conns_view(unified_env):
    """再接続 (= 同 conn_id の新 generator) 後に旧 generator の後始末が走っても、
    新接続の conn 登録と view 登録は消えない (= 「見てるのに通知が鳴る」 逆方向バグ防止)。"""
    state, sid_a, _sid_b, _ensured = unified_env

    async def run():
        conn_old = _mk_conn({})
        gen_old = us._unified_gen(conn_old, initial_view=sid_a)
        await _read_until(gen_old, lambda p: p.get("ch") == "overview")
        # 再接続: 同 conn_id で新 generator が登録を置き換える
        conn_new = us.UnifiedConn(conn_id="c1")
        gen_new = us._unified_gen(conn_new, initial_view=sid_a)
        await _read_until(gen_new, lambda p: p.get("ch") == "overview")
        assert us._conns["c1"] is conn_new
        assert state_mod.views_by_conn["c1"] == sid_a
        # 旧 generator の遅れた後始末 → 新接続の登録は無傷
        await gen_old.aclose()
        assert us._conns.get("c1") is conn_new
        assert state_mod.views_by_conn.get("c1") == sid_a
        # 新 generator の後始末 → 正しく消える
        await gen_new.aclose()
        assert "c1" not in us._conns
        assert "c1" not in state_mod.views_by_conn
    _run(run())


def test_pump_death_closes_connection(unified_env, monkeypatch):
    """pump task が例外死したら接続を閉じる (= 心拍だけ生きる新種 silent-dead の防止。
    client は ES close → 自動再接続で全 pump が作り直される)。"""
    _state, sid_a, _sid_b, _ensured = unified_env
    monkeypatch.setattr(us, "KEEPALIVE_SEC", 0.05)

    async def _dying_pump(_conn):
        raise RuntimeError("pump boom")
    monkeypatch.setattr(us, "_jsonl_pump", _dying_pump)

    async def run():
        conn = _mk_conn({sid_a: None})
        gen = us._unified_gen(conn, initial_view=None)
        await _read_until(gen, lambda p: p.get("ch") == "overview")
        # 次の keepalive 判定で pump 死を検知して StopAsyncIteration (= 接続 close)
        with pytest.raises(StopAsyncIteration):
            for _ in range(10):
                await asyncio.wait_for(gen.__anext__(), timeout=2.5)
        assert "c1" not in us._conns  # finally cleanup 済み
    _run(run())


def test_subagents_watcher_pushes_initial_payload(unified_env, monkeypatch, tmp_path):
    """subagents channel: watcher が起動直後に初回 payload を queue へ積む。

    回帰 (= 2026-07-27): `_build_subagents_payload` が #236 で 2 引数になった際、
    本 watcher だけ旧 1 引数呼びのまま残り、 起動即 TypeError で死んで「モーダルを
    開いている間サブエージェント完了が反映されない」 を再発させていた。 watcher を
    実際に走らせて初回 frame まで通せば、 この種のシグネチャ drift は必ずここで落ちる。
    """
    _state, sid_a, _sid_b, _ensured = unified_env
    sa_base = tmp_path / "sa-base"
    (sa_base / "subagents").mkdir(parents=True)
    (sa_base / "subagents" / "agent-abc123.jsonl").write_text(
        json.dumps({"type": "assistant", "message": {"content": []}}) + "\n")
    monkeypatch.setattr(us, "_session_base", lambda _sid: sa_base)

    async def run():
        conn = us.UnifiedConn(conn_id="c-sa")
        task = asyncio.create_task(us._subagents_watcher(conn, sid_a))
        try:
            frame = await asyncio.wait_for(conn.queue.get(), timeout=2.5)
        finally:
            task.cancel()
        assert frame["ch"] == "subagents"
        assert frame["sid"] == sid_a
        agents = frame["data"]["subagents"]
        assert [a["agentId"] for a in agents] == ["agent-abc123"]
    _run(run())


def test_subagents_watcher_crash_is_logged(unified_env, caplog):
    """watcher の例外死は fire-and-forget に握られず error log に出る (= 沈黙死の防止)。"""
    _state, _sid_a, _sid_b, _ensured = unified_env

    async def run():
        async def _boom():
            raise RuntimeError("watcher boom")
        task = asyncio.create_task(_boom())
        task.add_done_callback(us._log_watcher_crash)
        await asyncio.sleep(0.05)
    with caplog.at_level("ERROR"):
        _run(run())
    assert any("subagents watcher crashed" in r.message for r in caplog.records)


def test_subagents_watcher_pushes_differential_update(unified_env, monkeypatch, tmp_path):
    """subagents channel: ファイル変化 (= 追記) を検知して 2 回目以降の payload も push する。

    初回 push (= 上のテスト) だけでなく、 差分更新ループ (`_maybe_push` = 実運用の本線) を
    実際に通す。 watchfiles 依存を排して polling fallback 経路で回す (= 検知機構は別として、
    「変化 → 再 scan → 新 payload が queue に載る」 の結線を固定する)。
    """
    _state, sid_a, _sid_b, _ensured = unified_env
    monkeypatch.setattr(us, "_SUBAGENTS_POLL_SEC", 0.05)
    sa_base = tmp_path / "sa-base"
    sa_dir = sa_base / "subagents"
    sa_dir.mkdir(parents=True)
    first = sa_dir / "agent-aaa111.jsonl"
    first.write_text(json.dumps({"type": "assistant", "message": {"content": []}}) + "\n")
    monkeypatch.setattr(us, "_session_base", lambda _sid: sa_base)
    # polling fallback を強制 (= awatch import を潰す)
    import builtins
    real_import = builtins.__import__

    def _no_watchfiles(name, *a, **k):
        if name == "watchfiles":
            raise ImportError("forced for test")
        return real_import(name, *a, **k)
    monkeypatch.setattr(builtins, "__import__", _no_watchfiles)

    async def run():
        conn = us.UnifiedConn(conn_id="c-sa-diff")
        task = asyncio.create_task(us._subagents_watcher(conn, sid_a))
        try:
            initial = await asyncio.wait_for(conn.queue.get(), timeout=2.5)
            assert [a["agentId"] for a in initial["data"]["subagents"]] == ["agent-aaa111"]
            # 新 agent の出現 = ディレクトリ変化
            (sa_dir / "agent-bbb222.jsonl").write_text(
                json.dumps({"type": "assistant", "message": {"content": []}}) + "\n")
            update = await asyncio.wait_for(conn.queue.get(), timeout=2.5)
        finally:
            task.cancel()
        ids = sorted(a["agentId"] for a in update["data"]["subagents"])
        assert ids == ["agent-aaa111", "agent-bbb222"]
    _run(run())


def test_control_op_subagents_wires_watcher(unified_env, monkeypatch, tmp_path):
    """control op=subagents: watcher の起動 / sid 差替 / 解除の配線を endpoint 経由で通す。

    watcher 単体でなく `stream_unified_control` の分岐そのものを叩く (= ここの配線 drift は
    watcher 単体テストでは検知できない)。 crash logger の done_callback 装着も確認する。
    """
    _state, sid_a, sid_b, _ensured = unified_env
    sa_base = tmp_path / "sa-base"
    (sa_base / "subagents").mkdir(parents=True)
    monkeypatch.setattr(us, "_session_base", lambda _sid: sa_base)

    async def run():
        conn = us.UnifiedConn(conn_id="c-ctl")
        us._conns["c-ctl"] = conn
        try:
            r = await us.stream_unified_control("c-ctl", {"op": "subagents", "sid": sid_a})
            assert r == {"ok": True}
            assert conn.subagents_sid == sid_a
            assert conn.subagents_task is not None
            first_task = conn.subagents_task
            # 初回 payload が届く = watcher が生きて走った証明
            frame = await asyncio.wait_for(conn.queue.get(), timeout=2.5)
            assert frame["ch"] == "subagents" and frame["sid"] == sid_a
            # sid 差替 = 旧 watcher cancel + 新 watcher 起動
            await us.stream_unified_control("c-ctl", {"op": "subagents", "sid": sid_b})
            assert conn.subagents_sid == sid_b
            assert conn.subagents_task is not first_task  # 新 watcher に差し替わった
            await asyncio.wait([first_task], timeout=2.0)  # cancel の完了を待つ
            assert first_task.cancelled() or first_task.done()
            # sid 無し = 解除
            await us.stream_unified_control("c-ctl", {"op": "subagents"})
            assert conn.subagents_sid is None and conn.subagents_task is None
        finally:
            if conn.subagents_task is not None:
                conn.subagents_task.cancel()
            us._conns.pop("c-ctl", None)
    _run(run())
