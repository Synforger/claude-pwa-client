"""統合 stream (= 1 client 1 SSE 接続に全 channel を多重化、 2026-07-14 電力効率工事)。

旧構成はクライアント 1 台あたり SSE/WS を 4-5 本 (= /jsonl/stream/all +
/sessions/status/stream + /sessions/overview/stream + per-sid subagents + /views/ws)
常時張っていた。 本 endpoint はこれを 1 本の SSE + 制御 POST に畳む:

- GET  /stream/unified                : 多重化 SSE 本体 (= channel envelope で配信)
- POST /stream/unified/{conn}/control : 上り制御 (= jsonl 購読差替 / view 申告 / stop / subagents)

設計の柱:

1. **見ている sid だけ配る** (= 電力主犯だった全配信 fan-out の遮断)。 jsonl channel は
   接続時 query / control op で購読宣言された sid のみ流す。 タブ切替は再接続でなく
   「同一接続上で購読差替 + 差分 replay」。
2. **warmup も購読 sid だけ** (= 旧 /jsonl/stream/all は接続時に全 sid の PTY spawn を
   sweep していた。 未購読 sid は購読された時に ensure する)。
3. **views/ws の吸収**: 接続 = 生存。 SSE 切断で views 登録が自動消滅する性質は
   WS の TCP FIN と等価 (= stale 永久抑制バグが構造的に起きない)。
4. wire 契約: jsonl channel の `ev` は既存 sse-events.yaml の event をそのまま包む
   (= 中身の schema 変更なし)。 envelope 仕様は contracts/schema/unified-stream.yaml。

frame 形式 (= data 行 JSON、 SSE id 行は使わない。 offset は frame 内 pos が真値):

    {"ch":"sys","type":"hello","conn":"<id>"}
    {"ch":"sys","_hb":1}
    {"ch":"jsonl","pos":<int|null>,"ev":{...sse-event...}}
    {"ch":"status","data":{<sid>: {...}}}
    {"ch":"overview","data":{<sid>: {...}}}
    {"ch":"subagents","sid":"<sid>","data":{"subagents":[...],"workflows":[...]}}
"""
from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass, field

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse

from backend.core.jsonl_tail import read_complete_lines_with_pos
from backend.jsonl.events import jsonl_line_to_events
from backend.jsonl.routes import (
    _initial_offset,
    _inject_envelope,
    _latest_jsonl,
    _parse_all_from,
)
from backend.observability.metrics import metrics
from backend.routes.overview import (
    _build_all_status,
    _build_sessions_overview,
    _mark_user_stopped,
)
from backend.routes.subagents import (
    _awatch_with_heartbeat,
    _build_subagents_payload,
    _dir_signature,
    _payload_has_running,
    _session_base,
)
from backend.state import (
    ALL_SUBSCRIBER_KEY,
    jsonl_event_broadcaster,
    sessions_meta,
    sessions_overview,
    views_by_conn,
)

logger = logging.getLogger(__name__)

router = APIRouter()

# SSE keep-alive 間隔秒 (= jsonl/routes._SSE_KEEPALIVE_SEC と同方針。 client 側の黙死
# watchdog 65s に対して十分速い心拍。 test は monkeypatch で短縮する)。
KEEPALIVE_SEC = 25.0

# subagents watcher の fallback polling 間隔 (= watchfiles 不在環境)。
_SUBAGENTS_POLL_SEC = 1.0


@dataclass
class UnifiedConn:
    """1 client 接続分の状態 (= 購読 sid set + 配信 queue + 付随 task)。"""
    conn_id: str
    queue: asyncio.Queue = field(default_factory=asyncio.Queue)
    jsonl_sids: set[str] = field(default_factory=set)
    # 接続時 query で宣言された購読の replay 開始 offset (= generator が live pump 起動後に
    # file を読む。 GET handler 時点で読むと「構築〜pump 購読」 の隙間の publish が恒久欠落する)
    initial_offsets: dict[str, int | None] = field(default_factory=dict)
    subagents_sid: str | None = None
    subagents_task: asyncio.Task | None = None


# conn_id → UnifiedConn。 接続 generator が register / cleanup する (= 制御 POST は
# ここを引いて対象接続の queue / 購読 set を触る)。
_conns: dict[str, UnifiedConn] = {}


def _frame(obj: dict) -> str:
    return f"data: {json.dumps(obj, ensure_ascii=False)}\n\n"


async def _ensure_pty(sid: str) -> None:
    """購読 sid の claude 起動を保証 (= best-effort、 失敗は他 sid を巻き込まない)。"""
    from backend.terminal.routes import ensure_pty_session_for  # noqa: PLC0415
    try:
        await ensure_pty_session_for(sid)
    except Exception:
        # benign: PTY spawn is best-effort during subscribe; the tab still renders
        # from replayed history even if the spawn fails here.
        pass


def _replay_frames(sid: str, start: int | None) -> list[dict]:
    """1 sid の JSONL を start (= client offset、 無ければ直近 N 行) から event frame 化。

    per-line 実 byte pos を pos に載せる (= client は frame ごとに offset を前進できる)。
    prompt_state snapshot も末尾に付ける (= 切断中の遷移取りこぼしを接続時に収束、
    旧 per-sid / all SSE と同じ規約)。
    """
    frames: list[dict] = []
    path = _latest_jsonl(sid)
    if path is not None:
        try:
            size = path.stat().st_size
        except OSError:
            size = 0
        pos = start if (start is not None and 0 <= start <= size) else _initial_offset(path)
        # 久しぶりに購読された sid は client offset が大きく遅れている。 全区間 replay は
        # 表示上限 (= frontend MAX_MESSAGES) を大幅に超えて CPU を焼くだけなので、 直近
        # N 行 (= INITIAL_REPLAY_LINES) に clamp する (= それ以前は client の localStorage
        # cache が持っている)。
        pos = max(pos, _initial_offset(path))
        pairs, _new_pos = read_complete_lines_with_pos(path, pos)
        for raw, line_pos in pairs:
            raw = raw.strip()
            if not raw:
                continue
            try:
                obj = json.loads(raw)
            except json.JSONDecodeError:
                continue
            for event in jsonl_line_to_events(obj):
                _inject_envelope(event, sid)
                frames.append({"ch": "jsonl", "pos": line_pos, "ev": event})
    from backend.terminal.prompt_detector_loop import current_prompt_event  # noqa: PLC0415
    snap = _inject_envelope(current_prompt_event(sid), sid)
    frames.append({"ch": "jsonl", "pos": None, "ev": snap})
    return frames


async def _subagents_watcher(conn: UnifiedConn, sid: str) -> None:
    """subagents channel: sid の subagents/workflows 変化を watch して conn.queue へ push。

    実装は routes/subagents.py の per-sid SSE と同じ機構 (= watchfiles + signature 比較、
    ImportError 時は 1s polling fallback)。 初回 payload は即 push。
    """
    base = _session_base(sid)
    if base is None:
        return
    last_sig = _dir_signature(base)
    last_payload = _build_subagents_payload(base)
    await conn.queue.put({"ch": "subagents", "sid": sid, "data": last_payload})
    watch_targets = [d for d in (base / "subagents", base / "workflows") if d.is_dir()]
    try:
        from watchfiles import awatch  # noqa: PLC0415
    except ImportError:
        awatch = None

    async def _maybe_push() -> None:
        nonlocal last_sig, last_payload
        sig = _dir_signature(base)
        if sig != last_sig or _payload_has_running(last_payload):
            payload = _build_subagents_payload(base)
            if sig != last_sig or payload != last_payload:
                last_sig = sig
                last_payload = payload
                await conn.queue.put({"ch": "subagents", "sid": sid, "data": payload})

    if awatch is None or not watch_targets:
        while True:
            await asyncio.sleep(_SUBAGENTS_POLL_SEC)
            await _maybe_push()
    else:
        async for _ in _awatch_with_heartbeat(awatch, watch_targets, 5.0):
            await _maybe_push()


def _stop_subagents_watcher(conn: UnifiedConn) -> None:
    if conn.subagents_task is not None:
        conn.subagents_task.cancel()
        conn.subagents_task = None
    conn.subagents_sid = None


async def _status_pump(
    conn: UnifiedConn,
    ev: asyncio.Event,
    last_status: str | None,
    last_overview: str | None,
) -> None:
    """status / overview channel: sessions_overview broadcaster で起きて diff 配信。

    旧 /sessions/status/stream + /sessions/overview/stream の接続毎 diff (= F-09) と
    同じ規約を 1 task に統合 (= 変化が無い channel は流さない)。 ev は generator 側が
    初期 snapshot 構築**前**に subscribe 済み (= 構築と購読の隙間の notify 取りこぼしなし)、
    last_* は初期 snapshot の serialized 形 (= 初回 notify での重複配信を抑止)。
    """
    try:
        while True:
            await ev.wait()
            ev.clear()
            status_payload = json.dumps(_build_all_status())
            if status_payload != last_status:
                last_status = status_payload
                await conn.queue.put({"ch": "status", "data": json.loads(status_payload)})
            overview_payload = json.dumps(_build_sessions_overview())
            if overview_payload != last_overview:
                last_overview = overview_payload
                await conn.queue.put({"ch": "overview", "data": json.loads(overview_payload)})
    finally:
        sessions_overview.unsubscribe(ev)


async def _jsonl_pump(conn: UnifiedConn) -> None:
    """jsonl channel: broadcaster "all" を購読し、 conn の購読 sid だけ通す (= fan-out 遮断)。

    in-process の Queue 消費は sid フィルタ 1 発なので全 sid 分受けても負荷は無視できる。
    wire に乗るのは購読 sid のみ (= 未購読 sid の巨大 tool_result はネットワークにも
    client CPU にも一切届かない)。
    """
    q = jsonl_event_broadcaster.subscribe(ALL_SUBSCRIBER_KEY)
    try:
        while True:
            event, pos = await q.get()
            if (event.get("sid") or "") not in conn.jsonl_sids:
                continue
            await conn.queue.put({"ch": "jsonl", "pos": pos, "ev": event})
    finally:
        jsonl_event_broadcaster.unsubscribe(ALL_SUBSCRIBER_KEY, q)


async def _unified_gen(conn: UnifiedConn, initial_view: str | None):
    """統合 SSE generator 本体。 接続 = conn 登録、 切断 = 全 cleanup。"""
    _conns[conn.conn_id] = conn
    if initial_view:
        views_by_conn[conn.conn_id] = initial_view
    metrics.inc("sse.unified.connect")
    pumps: list[asyncio.Task] = []
    status_ev: asyncio.Event | None = None
    status_pump_started = False
    try:
        yield _frame({"ch": "sys", "type": "hello", "conn": conn.conn_id})

        # 1) live pump を replay より**先に**起動する (= 2026-07-15 修正: replay の file 読みと
        #    pump 購読の隙間に monitor が publish した行が恒久欠落していた。 pump 先行なら
        #    隙間の event は conn.queue に積まれ、 replay 後の live loop で配信される。
        #    replay と重複し得るが client の uuid dedup + offset 単調ガードが吸収する)
        status_ev = sessions_overview.subscribe()
        pumps.append(asyncio.create_task(_jsonl_pump(conn)))

        # 2) warmup + replay は購読 sid のみ (= 旧 /all の全 sid sweep を廃止)
        for sid in list(conn.jsonl_sids):
            await _ensure_pty(sid)
        for sid in sorted(conn.jsonl_sids):
            for f in _replay_frames(sid, conn.initial_offsets.get(sid)):
                yield _frame(f)
        conn.initial_offsets = {}

        # 3) 初期 snapshot (= status / overview。 旧 stream の接続直後 snapshot と同じ)。
        #    broadcaster の subscribe は上で済ませてある (= 隙間の notify 取りこぼしなし)
        initial_status = json.dumps(_build_all_status())
        initial_overview = json.dumps(_build_sessions_overview())
        yield _frame({"ch": "status", "data": json.loads(initial_status)})
        yield _frame({"ch": "overview", "data": json.loads(initial_overview)})

        # 4) status/overview diff pump 起動
        pumps.append(
            asyncio.create_task(_status_pump(conn, status_ev, initial_status, initial_overview)))
        status_pump_started = True

        # 4) 配信 loop (= queue 排出 + keep-alive + pump 死活監視)
        while True:
            try:
                item = await asyncio.wait_for(conn.queue.get(), timeout=KEEPALIVE_SEC)
            except asyncio.TimeoutError:
                # pump が例外死していないか確認してから心拍を打つ。 pump だけ死んで
                # 心拍が生き続けると、 client の生存監視 (= 65s watchdog) からは健康な
                # 接続に見えたまま chat 配信だけ止まる「新種の silent-dead」 になる。
                # 接続を切って client の自動再接続 (= 全 pump 作り直し) に回復させる。
                dead = [t for t in pumps if t.done()]
                if dead:
                    for t in dead:
                        exc = t.exception() if not t.cancelled() else None
                        if exc is not None:
                            logger.error("unified pump died: %r", exc)
                    metrics.inc("sse.unified.pump_dead_close")
                    return
                metrics.inc("sse.unified.keepalive")
                yield _frame({"ch": "sys", "_hb": 1})
                continue
            metrics.inc("sse.unified.frames")
            yield _frame(item)
    finally:
        metrics.inc("sse.unified.disconnect")
        for t in pumps:
            t.cancel()
        # replay 中の切断等で _status_pump 未起動のまま抜けた場合の購読 leak 掃除
        # (= 起動済みなら task 側 finally が unsubscribe する)
        if status_ev is not None and not status_pump_started:
            sessions_overview.unsubscribe(status_ev)
        _stop_subagents_watcher(conn)
        # 再接続で同 conn_id が新 generator に置き換わっている場合は一切消さない
        # (= 旧接続の遅れた後始末が新接続の view 登録を消すと、 「見てるのに通知が鳴る」
        # 逆方向バグになる。 views は conn 登録と同じ identity 判定で守る)
        if _conns.get(conn.conn_id) is conn:
            views_by_conn.pop(conn.conn_id, None)
            _conns.pop(conn.conn_id, None)


@router.get("/stream/unified")
async def stream_unified(request: Request):
    """多重化 SSE 本体。

    query:
      - conn  : client 生成の接続 id (= 制御 POST の宛先。 再接続時は同じ id を使い回す)
      - jsonl : `sid:off,sid:off,...` (= 初期購読 + replay 開始 offset。 offset 省略 sid は
                直近 N 行 fallback)
      - view  : 今見ている sid (= 通知抑制判定へ即反映)
    """
    conn_id = (request.query_params.get("conn") or "").strip()
    if not conn_id:
        raise HTTPException(status_code=422, detail="conn query param required")
    offsets = _parse_all_from(request.query_params.get("jsonl"))
    # offset 無し購読 (= `sid:` 形式でなく素の sid 列挙) も受ける: `jsonl=sid_a,sid_b:123`
    raw = request.query_params.get("jsonl") or ""
    for entry in raw.split(","):
        entry = entry.strip()
        if entry and ":" not in entry:
            offsets.setdefault(entry, None)  # type: ignore[arg-type]
    view = (request.query_params.get("view") or "").strip() or None

    conn = UnifiedConn(conn_id=conn_id)
    known = set(sessions_meta.keys())
    conn.jsonl_sids = {sid for sid in offsets if sid in known}
    conn.initial_offsets = {sid: offsets.get(sid) for sid in conn.jsonl_sids}
    return StreamingResponse(
        _unified_gen(conn, view),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.post("/stream/unified/{conn_id}/control")
async def stream_unified_control(conn_id: str, body: dict):
    """統合 stream の上り制御。 op:

    - {"op":"jsonl","sids":[{"sid":..,"from":<int|null>},..]} : 購読 set 差替。
      新規追加 sid は PTY ensure + from からの差分 replay を同一接続へ流す。
    - {"op":"view","sid":<sid|null>}   : 視認中 sid 申告 (= 通知抑制判定)
    - {"op":"stop","sid":<sid>}        : Stop 意思の権威記録 (= busy 強制 false)
    - {"op":"subagents","sid":<sid|null>} : subagents channel の対象 sid 切替 (null = 停止)
    """
    conn = _conns.get(conn_id)
    if conn is None:
        raise HTTPException(status_code=404, detail="unknown conn")
    op = body.get("op")

    if op == "jsonl":
        entries = body.get("sids") or []
        known = set(sessions_meta.keys())
        new_set: set[str] = set()
        froms: dict[str, int | None] = {}
        for e in entries:
            sid = (e or {}).get("sid")
            if isinstance(sid, str) and sid in known:
                new_set.add(sid)
                f = (e or {}).get("from")
                froms[sid] = f if isinstance(f, int) and f >= 0 else None
        added = new_set - conn.jsonl_sids
        # 順序: 先に live set へ加えてから replay (= 隙間ゼロ。 重複は client の uuid
        # dedup + offset 単調性が吸収する、 再接続 replay と同じ規約)
        conn.jsonl_sids = new_set
        for sid in sorted(added):
            await _ensure_pty(sid)
            for f in _replay_frames(sid, froms.get(sid)):
                await conn.queue.put(f)
        return {"ok": True, "subscribed": sorted(new_set)}

    if op == "view":
        sid = body.get("sid")
        if isinstance(sid, str) and sid:
            views_by_conn[conn_id] = sid
        else:
            views_by_conn.pop(conn_id, None)
        return {"ok": True}

    if op == "stop":
        sid = body.get("sid")
        if not (isinstance(sid, str) and sid):
            raise HTTPException(status_code=422, detail="sid required")
        return {"ok": _mark_user_stopped(sid)}

    if op == "subagents":
        sid = body.get("sid")
        _stop_subagents_watcher(conn)
        if isinstance(sid, str) and sid:
            conn.subagents_sid = sid
            conn.subagents_task = asyncio.create_task(_subagents_watcher(conn, sid))
        return {"ok": True}

    raise HTTPException(status_code=422, detail=f"unknown op: {op}")
