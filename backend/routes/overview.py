"""全 sid を 1 接続で配信する status / overview SSE + views/ws (= 旧 chat.py から分割、
backend-F-28 / crosscut-F-04)。

責務:
- GET  /sessions/status/stream     : 全 sid status 1 接続 SSE
- GET  /sessions/overview/stream   : 全 sid busy / pending overview 1 接続 SSE
- POST /sessions/{sid}/seen        : 「今このタブを見た」 を全端末 sync
- WS   /views/ws                   : 「今どの sid を見てるか」 を realtime に伝える

実装の重要 invariants:
- F-09 接続ごとの diff 配信: subscribe で起きても snapshot に変化が無ければ data 行を
  yield しない (= 全接続 wake で帯域消費しない、 retry tick だけは 20s 毎に comment 行で
  keep-alive)。
- F-10 keep-alive 軽量化: 20s timeout は SSE comment 行 (= `:\n\n`) のみで返す。 全 sid 分の
  JSON を毎 20s 流すのは無駄 (= 状態変化がある時のみ data 行)。
- F-56 rate-limits memoize: status SSE は接続数 × notify 回 read を 1 秒 cache に縮める。
"""
from __future__ import annotations

import asyncio
import json
import logging
import time

from fastapi import APIRouter, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import StreamingResponse

from backend.core.usage import read_all_rate_limits_tail
import backend.jsonl.watcher as jsonl_watcher
from backend import state
from backend.state import (
    agent_status,
    backend_start_time,
    session_last_seen_at,
    sessions_meta,
    sessions_overview,
    shared_status,
    stream_states,
    views_by_conn,
)

logger = logging.getLogger(__name__)

router = APIRouter()


# --- rate-limits memoize (= backend-F-56) ---
# `_build_all_status` は SSE 接続ごとの notify で都度呼ばれる。 1 接続あたり 32KB tail
# read + 200 行 parse は軽いが、 全 sid status を返す 1 接続 + 全 sid overview を返す
# 1 接続 + per-sid status SSE が複数同時 wake する状況だと同 tail を 1 秒以内に数十回
# parse する。 file は 1 秒に 1 回程度しか rotate / append されないので 1s memoize で
# I/O / parse を最大 1 round-trip / 秒 に固定する。
_RATE_TAIL_CACHE: tuple[float, list[dict]] = (0.0, [])
_RATE_TAIL_TTL_SEC = 1.0


def _read_rate_limits_tail_cached() -> list[dict]:
    """1 秒 memoize した rate-limits tail。 connection burst で同 tail を多重 parse しない。"""
    global _RATE_TAIL_CACHE
    now = time.monotonic()
    ts, cached = _RATE_TAIL_CACHE
    if now - ts < _RATE_TAIL_TTL_SEC and cached:
        return cached
    fresh = read_all_rate_limits_tail()
    _RATE_TAIL_CACHE = (now, fresh)
    return fresh


def _build_all_status() -> dict:
    """全 session の status を 1 dict で返す (= /sessions/status/stream payload)。

    rate-limits.jsonl は **1 ファイル**で全 session 共有。 sid 毎に read_latest_rate_limits
    を呼ぶと 32KB tail を sid 数回 read + parse することになり、 重い + 一瞬古い値が
    混じって status line がちらつく。 1 回 read + parse して、 sid 毎は dict lookup だけ
    にする (= O(read) + O(sid) で済む)。"""
    parsed = _read_rate_limits_tail_cached()  # 1s memoize、 接続 burst で多重 parse しない
    # account 別に集計 (= 並走中の個人 / 会社で 5h / 7d が混ざらないように)。
    # rate-limits.jsonl の各 record は account_id ("personal" / "work" / ...) を持つ。
    # 旧版で account_id 欠落の record は "personal" 扱い (= 単一 OAuth 運用との互換)。
    by_acct: dict[str, list[dict]] = {}
    by_sess: dict[str, dict] = {}
    for p in parsed:
        acct = p.get("account_id") or "personal"
        by_acct.setdefault(acct, []).append(p)
        sid_key = p.get("session_id")
        if sid_key:
            by_sess[sid_key] = p  # 最後勝ち = 各 claude_sid の最新行

    def _acct_view(acct: str) -> tuple[dict, float | int | None]:
        ps = by_acct.get(acct) or []
        if not ps:
            return {}, None
        last_p = ps[-1]
        cur_reset = last_p.get("seven_day_resets_at")
        same_window = [
            p.get("seven_day_pct") for p in ps
            if p.get("seven_day_resets_at") == cur_reset
            and isinstance(p.get("seven_day_pct"), (int, float))
        ]
        seven_pct = max(same_window) if same_window else last_p.get("seven_day_pct")
        return last_p, seven_pct

    out: dict[str, dict] = {}
    for sid in list(sessions_meta.keys()):
        meta = sessions_meta[sid]
        acct = meta.account_id or "personal"
        a = agent_status[sid]
        jp = jsonl_watcher.get_jsonl_for(sid)
        claude_sid = jp.stem if jp else None
        sess = by_sess.get(claude_sid) if claude_sid else None
        last_acct, seven_day_pct_acct = _acct_view(acct)
        out[sid] = {
            "model": (sess.get("model") if sess else None) or a["model"],
            "ctx_pct": (sess.get("context_pct") if sess and sess.get("context_pct") is not None else a["ctx_pct"]),
            "plan_mode": a["plan_mode"],
            "current_tool": a["current_tool"],
            "todos": a["todos"],
            "subagent": a["subagent"],
            "pending_plan": a.get("pending_plan"),
            "pending_question": a.get("pending_question"),
            "mode": a.get("mode") or "",
            "permission_mode": a.get("permission_mode") or "",
            "budget_used": a.get("budget_used"),
            "budget_total": a.get("budget_total"),
            "budget_remaining": a.get("budget_remaining"),
            "pr_links": a.get("pr_links") or [],
            "tasks": a.get("tasks") or [],
            "five_hour_pct": last_acct.get("five_hour_pct") if last_acct.get("five_hour_pct") is not None else shared_status["five_hour_pct"],
            "seven_day_pct": seven_day_pct_acct if seven_day_pct_acct is not None else shared_status["seven_day_pct"],
            "five_hour_resets_at": last_acct.get("five_hour_resets_at") or shared_status["five_hour_resets_at"],
            "seven_day_resets_at": last_acct.get("seven_day_resets_at") or shared_status["seven_day_resets_at"],
            "account_id": acct,
            "backend_start_time": backend_start_time,
        }
    return out


def _build_sessions_overview() -> dict:
    """全 session の busy / pending_question + last_seen_at を 1 dict で返す
    (= /sessions/overview/stream payload)。

    busy は monitor_all_sessions_loop が JSONL から算出した backend 権威値 (= chat SSE の
    result 配信に依存しない)。 frontend は各 sid の busy で loading を上書きして、 青丸
    (処理中) / 赤丸 (完了未読) / 停止ボタンを **非アクティブタブでも** live 追従させる。

    last_seen_at は他端末がそのタブを開いた時刻 (= unix sec)。 各 client は自分の最新
    received event timestamp と比較して、 last_seen_at が新しければ赤丸を消す
    (= iPhone と Mac の未読同期、 2026-06-10 追加)。"""
    out: dict[str, dict] = {}
    for sid in list(sessions_meta.keys()):
        st = stream_states.get(sid)
        a = agent_status.get(sid) or {}
        out[sid] = {
            "busy": bool(st.busy) if st is not None else False,
            "pending_question": bool(a.get("pending_question")),
            "last_seen_at": session_last_seen_at.get(sid),
        }
    return out


def _mark_user_stopped(session_id: str) -> bool:
    """ユーザ Stop 意思を backend の権威 state に書く。 /views/ws の stop メッセージ
    から呼ばれる (= HTTP POST 経由は廃止、 WebSocket で確実に届ける構造)。

    SessionState 経由で user_stopped + busy を権威 stream に書く (= backend-F-07、
    consumer 移行の第一歩)。 SessionState 未登録だが旧 stream_states 直登録された
    互換ケースもあるため、 sess が無ければ stream_states に直接 fallback する。 同期
    handler から呼ばれるので async lock は取らない (= mutate は単純 2 bool で GIL 内 atomic)。"""
    sess = state.get_session(session_id)
    st = sess.stream if sess is not None else stream_states.get(session_id)
    if st is None:
        return False
    st.user_stopped = True
    if st.busy:
        st.busy = False
    sessions_overview.notify()
    return True


@router.get("/sessions/status/stream")
async def all_status_stream():
    """全 sid の status を 1 接続で配信する SSE (= タブ切替で SSE 張り替え不要)。

    sessions_overview と同じ broadcaster で起きる (= 任意 sid の status_event.set() で
    全接続が再 push)。 frontend は活用 sid を切り替えても接続をそのまま使えるので、
    iOS Safari の 1-3s SSE 確立コストがタブ切替体験から消える。

    F-09 接続毎 diff: 接続ごとに直前 snapshot を保持し、 変化が無ければ data 行を
    yield しない (= 全接続 wake で帯域を空転消費しない)。 20s timeout の keep-alive は
    SSE comment 行 (= `:\n\n`) のみ (F-10)、 状態変化を含まない無駄な data 行は流さない。"""
    async def gen():
        ev = sessions_overview.subscribe()
        last_payload: str | None = None
        try:
            initial = _build_all_status()
            initial_payload = json.dumps(initial)
            yield f"retry: 3000\n\ndata: {initial_payload}\n\n"
            last_payload = initial_payload
            while True:
                try:
                    await asyncio.wait_for(ev.wait(), timeout=20.0)
                    ev.clear()
                    snap = json.dumps(_build_all_status())
                    if snap != last_payload:
                        yield f"data: {snap}\n\n"
                        last_payload = snap
                except asyncio.TimeoutError:
                    # keep-alive: comment 行のみ (F-10)。 data 行は変化時のみ。 5h/7d
                    # 更新は notify() で run-through するので 20s tick で全 sid 再 push
                    # する旧挙動は不要。
                    yield ": ka\n\n"
        finally:
            sessions_overview.unsubscribe(ev)

    return StreamingResponse(
        gen(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.post("/sessions/{session_id}/seen")
def mark_session_seen(session_id: str) -> dict:
    """指定 session を「今この瞬間に確認した」 とマークし、 全端末に sync 配信する。

    frontend は自タブを activeSid 化したタイミング (= タブ切替時) に POST する。 backend は
    session_last_seen_at[sid] を now で更新して sessions_overview.notify() で broadcast。
    他端末はこの時刻と自分が見た最後のメッセージ timestamp を比較して、 last_seen_at が
    新しければ赤丸を消す。"""
    if session_id not in sessions_meta:
        raise HTTPException(status_code=404, detail="Unknown session")
    session_last_seen_at[session_id] = time.time()
    sessions_overview.notify()
    return {"ok": True, "last_seen_at": session_last_seen_at[session_id]}


@router.get("/sessions/overview/stream")
async def sessions_overview_stream():
    """全 session の busy / pending を 1 本で push する SSE (= 案 B)。

    タブごとに SSE を張らず 1 接続で全 session をカバーするので、 session 数が増えても
    接続は 1 本のまま (= リソース増加なし)。 sessions_overview.notify() のたびに最新 snapshot
    を yield。 20 秒の timeout で keep-alive 兼 定期同期。

    接続ごとに専用 Event を購読するので、 複数デバイス同時でも 1 接続の clear() が他接続の
    push を奪わない (= 旧 単一 Event 共有時の取りこぼしを解消)。

    F-09 接続毎 diff: payload 不変なら data 行を yield しない (= status SSE と同方針)。
    F-10 keep-alive は SSE comment 行のみ。"""
    async def gen():
        # 接続ごとに専用 Event を購読 (= 複数デバイス同時でも push を取りこぼさない)。
        ev = sessions_overview.subscribe()
        last_payload: str | None = None
        try:
            # 接続直後に snapshot を 1 chunk で送る (= retry + 初期 data を結合)。
            initial = json.dumps(_build_sessions_overview())
            yield f"retry: 3000\n\ndata: {initial}\n\n"
            last_payload = initial
            while True:
                try:
                    await asyncio.wait_for(ev.wait(), timeout=20.0)
                    ev.clear()
                    snap = json.dumps(_build_sessions_overview())
                    if snap != last_payload:
                        yield f"data: {snap}\n\n"
                        last_payload = snap
                except asyncio.TimeoutError:
                    yield ": ka\n\n"
        finally:
            sessions_overview.unsubscribe(ev)

    return StreamingResponse(
        gen(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.websocket("/views/ws")
async def views_ws(ws: WebSocket):
    """frontend が「今どの session を見ているか」 を realtime に backend に伝える経路。

    接続中の間 sid を保持し、 broadcast_push の `is_session_viewed` 判定に使う。
    TCP FIN / iOS が PWA bg 化時に socket を切るタイミングで自動削除されるので、
    stale state 永久抑制バグが構造的に起きない。

    プロトコル: client が JSON メッセージで随時送信:
      - `{"sid": "ses_xxx" | null}`: 今見ている sid を更新 (タブ切替で再送)
      - `{"type": "stop", "sid": "ses_xxx"}`: Stop ボタン押下の権威記録。 backend が
        user_stopped=True を立てて busy を強制 false に。 WebSocket 経由なので HTTP の
        POST 失敗 race が原理的に無い (= 接続中なら TCP 保証で届く)。
    """
    # conn_id は uuid (= id(ws) は GC 後再利用で別接続と衝突する余地があるため不採用)。
    import uuid as _uuid  # noqa: PLC0415
    conn_id = _uuid.uuid4().hex
    try:
        await ws.accept()
        while True:
            text = await ws.receive_text()
            try:
                payload = json.loads(text)
            except (ValueError, TypeError):
                continue
            if not isinstance(payload, dict):
                continue
            msg_type = payload.get("type")
            sid = payload.get("sid")
            if msg_type == "stop" and isinstance(sid, str) and sid:
                _mark_user_stopped(sid)
                continue
            # default: view 更新
            if isinstance(sid, str) and sid:
                views_by_conn[conn_id] = sid
            else:
                views_by_conn.pop(conn_id, None)
    except WebSocketDisconnect:
        pass
    finally:
        views_by_conn.pop(conn_id, None)
