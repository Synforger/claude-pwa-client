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
import logging
import time

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse

from backend.core.usage import latest_from_tail, read_all_rate_limits_tail
import backend.core.jsonl_watcher as jsonl_watcher
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
    # 各 claude_sid の最新行を dict lookup できるように map 化 (= 5h/7d 以外の per-session
    # 値 ctx/model はこの経路から取る)。 account 別集計 (= 5h/7d) は下記 _acct_view で
    # core/usage.latest_from_tail に委譲、 二重実装によるドリフト防止 (= PR #46/#47 経緯)。
    by_sess: dict[str, dict] = {}
    for p in parsed:
        sid_key = p.get("session_id")
        if sid_key:
            by_sess[sid_key] = p  # 最後勝ち = 各 claude_sid の最新行

    def _acct_view(acct: str) -> tuple[dict, float | int | None]:
        # 5h/7d/resets_at の集計は core/usage.latest_from_tail に一元化。 過去に本 file が
        # 同ロジックを inline で持ち、 max hack の flap 吸収が usage.py 側だけ撤去されて
        # 本 file 側に残った結果 PWA statusline が真値を追えない事故が起きた (2026-07-02)。
        # ここは delegate に徹し、 挙動変更が要る場合は core/usage.py 側で行う。
        view = latest_from_tail(parsed, account_id=acct)
        return view, view.get("seven_day_pct")

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
    """全 session の busy + last_seen_at を 1 dict で返す
    (= /sessions/overview/stream payload)。

    busy は JSONL 由来の権威値 (= monitor_all_sessions_loop が算出) と、 画面の実況
    (= prompt_detector_loop が観測する TUI 推論中スピナー、 StreamState.pane_working) の
    **OR**。 「推論中 = claude が考えている時」 が原義で、 JSONL 簿記が拾えない queue 消化中の
    無言時間もスピナーが回っていれば busy=true を維持する。 frontend は各 sid の busy で
    loading を上書きして、 青丸 (処理中) / 赤丸 (完了未読) / 停止ボタンを **非アクティブ
    タブでも** live 追従させる。 user_stopped (= Stop 押下) は両者に優先して false。

    last_seen_at は他端末がそのタブを開いた時刻 (= unix sec)。 各 client は自分の最新
    received event timestamp と比較して、 last_seen_at が新しければ赤丸を消す
    (= iPhone と Mac の未読同期、 2026-06-10 追加)。"""
    from backend.terminal.prompt_detector_loop import is_waiting_input  # noqa: PLC0415
    out: dict[str, dict] = {}
    for sid in list(sessions_meta.keys()):
        st = stream_states.get(sid)
        a = agent_status.get(sid) or {}
        if st is None:
            busy = False
        elif st.user_stopped:
            busy = False
        else:
            busy = bool(st.busy or st.pane_working)
        out[sid] = {
            "busy": busy,
            "last_seen_at": session_last_seen_at.get(sid),
            # 入力待ち (= AskUserQuestion / TUI 選択肢) の軽量フラグ。 統合 transport は
            # 未購読 sid の chat event を配らないため、 ドロワーの質問待ちバッジの
            # 裏セッション分はこのフラグが真値 (= detector は全 sid 常時監視)。
            "waiting_input": is_waiting_input(sid),
        }
    return out


def _mark_user_stopped(session_id: str) -> bool:
    """ユーザ Stop 意思を backend の権威 state に書く。 /views/ws の stop メッセージ
    から呼ばれる (= unified stream の control op=stop 経由、 2026-07-27 に旧 /views/ws は退役)。

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
