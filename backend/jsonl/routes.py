"""claude の JSONL ログを tail して SSE で配信する route (= chat UI の出力側)。

claude を PTY/TUI 経路で動かすと、 会話の全 turn が構造化された JSONL
(`~/.claude/projects/<cwd-hash>/<claude_session_id>.jsonl`) に追記される。 これを
backend が tail し、 jsonl_events で processStreamEvent.js の event 形式に変換して
SSE で流すことで、 proxy/SDK/`-p` を一切使わず (= subscription 枠・軽い) chat UI を
再構成できる。

入出力分離: 出力 (= 表示) はこの SSE、 入力 (= キー送信) は pty_routes の WebSocket。

wire (= SSE):
    data: {<processStreamEvent event>}\n\n   会話 event (assistant / user / result 等)
    : keep-alive\n\n                          ハートビート (= idle 時)
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse

from backend.jsonl.events import jsonl_line_to_events
from backend.jsonl.notifications import maybe_push_blockers as _maybe_push_blockers
from backend.jsonl.session_status import (
    attach_duration_to_result as _attach_duration_to_result,
    busy_after_idle as _busy_after_idle,
    compute_busy_from_tail as _compute_busy_from_tail,
    is_user_prompt as _is_user_prompt,
    latest_subagent_tool as _latest_subagent_tool,
    mutate_agent_status as _mutate_agent_status,
    refresh_subagent_status as _refresh_subagent_status,
    track_turn_start as _track_turn_start,
    update_busy as _update_busy,
)
from backend.jsonl.tail import (
    initial_offset as _initial_offset_impl,
    read_complete_lines as _read_complete_lines,
    read_tail as _read_tail,
)
from backend.terminal.runner import jsonl_path_for_session
from backend.state import agent_status, sessions_overview, stream_states


logger = logging.getLogger(__name__)

router = APIRouter()

# 初回接続時に遡って replay する最大行数。 frontend は localStorage に最終 byte offset を
# 保存して `?from=<offset>` で渡してくるので、 これは初訪問 / localStorage が消えた時の
# フォールバックとして使われる。
INITIAL_REPLAY_LINES = 500

# tail の polling 間隔 (秒)。
POLL_INTERVAL = 0.5

# idle 時の back-off 上限秒。 SSE / monitor とも同じ値を使う (= backend-F-42 で統合)。
_IDLE_MAX_INTERVAL = 2.0
# back-off の伸び率 (= 変化なし時、 current * GROWTH で次回間隔を伸ばす)。
_IDLE_GROWTH = 1.5


def next_interval(current: float, made_progress: bool) -> float:
    """idle back-off helper (= backend-F-42)。 旧 SSE 配信 (`_jsonl_sse`) と push 監視
    (`monitor_all_sessions_loop`) で「変化あれば base / 無ければ 1.5x ずつ伸ばす (上限 2s)」
    の同じロジックが 2 箇所に書かれていた。 ここに集約する。

    made_progress=True (= 行追加された / busy 維持中) は次 tick も base 間隔で叩く、
    False (= 完全 idle) なら current を 1.5 倍に伸ばす (上限 _IDLE_MAX_INTERVAL)。
    """
    if made_progress:
        return POLL_INTERVAL
    return min(current * _IDLE_GROWTH, _IDLE_MAX_INTERVAL)

# idle watchdog: busy=True のまま JSONL がこの秒数以上 静かなら file 真値で busy を照合し直す。
# 通常 (= 終端 stop_reason 行が書かれる) は monitor が即 busy=False にするので発火しない。
# 終端マーカー欠落 (claude-code #22566) / monitor の取りこぼし のバックストップ。 長時間の
# ツール実行 (= 末尾が tool_use) は busy_after_idle が True を返すので誤って解除しない。
# 体感即時化のため 15→5 に短縮 (= 2026-06-16、 watchdog コスト = 末尾 32KB の read+parse のみで軽い)。
WATCHDOG_IDLE_SEC = 5.0


def _latest_jsonl(session_id: str) -> Path | None:
    """PWA session_id から claude JSONL を解決する。

    実装は pty_runner.jsonl_path_for_session (= tmux pane → claude PID → lsof で
    open file を直接取得) に委譲する。 同じ cwd で動く他の claude プロセス
    (Claude Desktop App / ターミナル直叩き) の JSONL を絶対に拾わない。

    解決失敗時 (= tmux 未生成 / claude 未起動 / lsof で JSONL 未検出) は None。
    """
    return jsonl_path_for_session(session_id)


def _lines_to_sse(lines: list[str], pos: int, session_id: str) -> list[str]:
    """JSONL 行 (文字列) のリストを SSE フレームのリストに変換する。

    各フレームに `id: <pos>` (= この行群を読み終えた後のバイト位置) を付ける。 EventSource は
    受信した最後の id を保持し、 再接続時に `Last-Event-ID` ヘッダで送るので、 backend は
    そこから続きだけ流せる (= backend 再起動後の全 replay を回避)。

    副作用: 各行で `_mutate_agent_status` を呼び、 todos / plan_mode / current_tool /
    ctx_pct / model を更新する。 変化があれば最後に status_event.set() を打って
    `/status/{sid}/stream` SSE を即時 push (= ActivityBar / StopReasonChip を再描画)。
    """
    frames: list[str] = []
    state = stream_states.get(session_id)
    status_dirty = False
    for raw in lines:
        raw = raw.strip()
        if not raw:
            continue
        try:
            obj = json.loads(raw)
        except json.JSONDecodeError:
            continue
        _track_turn_start(session_id, obj)
        if _mutate_agent_status(session_id, obj):
            status_dirty = True
        # 通知 push 発火 (= _maybe_push_blockers) は SSE 経路で呼ばない。 別 lifespan task の
        # monitor_all_sessions_loop が全 sid を常時 tail して push を担当 (= PWA 接続有無に
        # 関係なく通知発火させるため + SSE 経路との二重発火回避)。
        evts = jsonl_line_to_events(obj)
        _attach_duration_to_result(session_id, obj, evts)
        for event in evts:
            frames.append(f"id: {pos}\ndata: {json.dumps(event, ensure_ascii=False)}\n\n")
    if status_dirty and state is not None:
        state.status_event.set()
        sessions_overview.notify()  # 全 sid SSE (/sessions/status/stream) にも伝播
    return frames


def _initial_offset(path: Path) -> int:
    """thin wrapper: tail.initial_offset(path, INITIAL_REPLAY_LINES) (= backend-F-41 で移送済)。
    既存 test (test_jsonl_routes.py) との後方互換のために残す。 新規 consumer は
    `backend.jsonl.tail.initial_offset` を直接 import すること。"""
    return _initial_offset_impl(path, INITIAL_REPLAY_LINES)


async def _jsonl_sse(session_id: str, start_pos: int | None = None):
    # チャット画面のみ開いてターミナル画面に切り替えていないタブでも claude を起動させる。
    # 既に tmux + claude が動いていれば no-op。
    from backend.terminal.routes import ensure_pty_session_for
    await ensure_pty_session_for(session_id)

    # 初回起動直後 (= ensure_pty_session_for で spawn したが claude が SessionStart hook で
    # binding を確定するまでの数秒) は path が解決できない。 即 error 返して generator を終了
    # すると EventSource が再接続を繰り返して「ターミナルは動いてるが chat 空」 状態になる。
    # 代わりに keep-alive を流しながら最大 15 秒 path 解決を待つ (= hook が間に合わなければ
    # 諦めて error)。
    path = _latest_jsonl(session_id)
    if path is None:
        for _ in range(30):  # 0.5s × 30 = 15s
            await asyncio.sleep(POLL_INTERVAL)
            path = _latest_jsonl(session_id)
            if path is not None:
                break
            yield ": waiting-for-jsonl\n\n"
        if path is None:
            yield f"data: {json.dumps({'type': 'error', 'message': 'no JSONL found for session'})}\n\n"
            return

    try:
        size = path.stat().st_size
    except OSError:
        size = 0
    # 再接続 (= Last-Event-ID あり) は続きから、 初回は直近 N 行に絞る。
    # start_pos がファイルサイズを超える (= 別ファイルに切り替わった等) 場合は初回扱い。
    if start_pos is not None and 0 <= start_pos <= size:
        pos = start_pos
    else:
        pos = _initial_offset(path)

    # 初回 replay (= 再接続時は start_pos 以降のみ = 差分)
    lines, pos = _read_complete_lines(path, pos)
    for frame in _lines_to_sse(lines, pos, session_id):
        yield frame

    # tail: 新規追記行を追従する (= stat/truncate/read は _read_tail に集約)。
    # idle が続いたら sleep を伸ばして disk I/O / CPU を減らす (= base 0.5s → 最大 2s)。
    # 変化が来たら即 base に戻す。
    idle_sleep = POLL_INTERVAL
    while True:
        await asyncio.sleep(idle_sleep)
        lines, pos, status = _read_tail(path, pos)
        if status == "error":
            # ファイルが消えた (= セッション破棄等) → 終了
            return
        if status == "truncated":
            # truncate / rotate → 先頭から読み直す
            lines, pos, status = _read_tail(path, 0)
        emitted = False
        if status == "ok":
            for frame in _lines_to_sse(lines, pos, session_id):
                yield frame
                emitted = True
        # Task 実行中は main JSONL が静かでも subagent は別ファイルで動くので毎 tick 追う。
        # 変化があれば status_event を叩いて /status SSE 経由で last_tool を push する。
        subagent_changed = _refresh_subagent_status(session_id, path)
        if subagent_changed:
            st = stream_states.get(session_id)
            if st is not None:
                st.status_event.set()
                sessions_overview.notify()  # 全 sid SSE にも伝播
        # busy 中の sid は back-off せず base 間隔のまま (= end_turn 行を即時拾って
        # busy=false 遷移を遅延させない)。 back-off ロジック自体は next_interval helper
        # に集約 (= backend-F-42、 monitor 側も同じ helper を共有)。
        st_bk = stream_states.get(session_id)
        is_busy_now = st_bk is not None and st_bk.busy and not st_bk.user_stopped
        idle_sleep = next_interval(idle_sleep, emitted or subagent_changed or is_busy_now)
        if not emitted:
            yield ": keep-alive\n\n"


@router.get("/jsonl/_debug/bindings")
async def jsonl_debug_bindings() -> dict:
    """debug: 現在 backend mem に持ってる watcher binding 一覧。"""
    import backend.jsonl.watcher as jsonl_watcher
    return jsonl_watcher.list_bindings()


@router.get("/jsonl/stream/{session_id}")
async def jsonl_stream(session_id: str, request: Request):
    """指定 PWA session の claude JSONL を tail して SSE で event を流す。

    再接続時は EventSource が送る `Last-Event-ID` (= 前回読み終えた byte 位置) から
    続きだけ流し、 backend 再起動後の全 replay を避ける。
    """
    # 再開位置: EventSource 自動再接続の Last-Event-ID を優先、 無ければ ?from クエリ
    # (= タブ切替で frontend が保持した offset から差分取得する経路)。
    src = request.headers.get("last-event-id") or request.query_params.get("from")
    start_pos: int | None = None
    if src:
        try:
            start_pos = int(src)
        except (ValueError, TypeError):
            start_pos = None
    return StreamingResponse(
        _jsonl_sse(session_id, start_pos),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# --- 常時 tail (= PWA 接続有無に関係なく動く push 発火経路) ---
# backend の lifespan task として全 PWA session の JSONL を polling し、
# AskUserQuestion 発火 / stop_reason 異常を検出して Web Push を飛ばす。
# SSE 経路 (= /jsonl/stream) の _maybe_push_blockers 呼び出しは廃止済 (= 二重発火回避)。
async def monitor_all_sessions_loop():
    """全 PWA session の JSONL を常時 tail し、 推論を止める要因を検出して push 発火する。

    起動時は各 sid を末尾 offset から開始する (= backend 起動前の過去行は通知しない)。
    `/clear` 等で claude_sid が切り替わると `_latest_jsonl` が新 path を返すので、
    そのときは新 path の末尾から再開する。 file が縮んだ (rotate / truncate) 場合も
    同様に末尾再同期。

    State: state[sid] = (path, byte_offset)。 SSE 経路の `offsetRef` とは独立した
    バックエンド内の追跡 (= frontend の localStorage が消えても影響を受けない)。
    """
    state: dict[str, tuple[Path, int]] = {}
    # sid → 最後に新規 JSONL 行を処理した monotonic 時刻 (= idle watchdog 用)。
    last_line_at: dict[str, float] = {}
    # idle session の poll を back-off するための per-sid 状態。
    # 変化が来たら base に戻し、 nochange が続いたら 1.5x ずつ伸ばす (上限 2s)。
    sid_interval: dict[str, float] = {}
    next_poll_at: dict[str, float] = {}
    logger.info("monitor_all_sessions_loop started")
    try:
        while True:
            try:
                await asyncio.sleep(POLL_INTERVAL)
                from backend.state import sessions_meta as _sessions_meta  # 動的参照
                # 削除済み session の追跡 entry を刈り取る (= 無停止運用での単調増加防止)
                for stale in [s for s in state if s not in _sessions_meta]:
                    state.pop(stale, None)
                    last_line_at.pop(stale, None)
                    sid_interval.pop(stale, None)
                    next_poll_at.pop(stale, None)
                now_mono = time.monotonic()
                for sid in list(_sessions_meta.keys()):
                    # idle back-off: 該当 sid の次 poll 時刻に達してなければスキップ
                    if next_poll_at.get(sid, 0.0) > now_mono:
                        continue
                    path = _latest_jsonl(sid)
                    if path is None:
                        # path 未解決 sid は base interval で次回再試行
                        next_poll_at[sid] = now_mono + POLL_INTERVAL
                        continue
                    prev = state.get(sid)
                    if prev is None or prev[0] != path:
                        # 初回 or path 切替: 末尾から開始 (= 過去行を再通知しない)
                        try:
                            state[sid] = (path, path.stat().st_size)
                        except OSError:
                            pass
                        # path 切替時 (= /clear / resume / フォーク等で claude session が
                        # 入れ替わった時) は jsonl 由来の蓄積メタを空に戻す。 これで前 session
                        # の PR や task list が新 session に持ち越されない (2026-06-12)。
                        if prev is not None and prev[0] != path:
                            a = agent_status.get(sid)
                            if a is not None:
                                if a.get("pr_links"):
                                    a["pr_links"] = []
                                if a.get("tasks"):
                                    a["tasks"] = []
                                st_reset = stream_states.get(sid)
                                if st_reset is not None:
                                    st_reset.status_event.set()
                                    sessions_overview.notify()
                        # busy は過去行を通知しない代わりに末尾から現在値を 1 回算出する
                        # (= backend 起動時に推論中だった session も正しく busy=True にする)。
                        st = stream_states.get(sid)
                        if st is not None:
                            new_busy = _compute_busy_from_tail(path)
                            if st.user_stopped:
                                new_busy = False
                            if new_busy != st.busy:
                                st.busy = new_busy
                                sessions_overview.notify()
                        last_line_at[sid] = time.monotonic()
                        continue
                    lines, new_pos, status = _read_tail(path, prev[1])
                    if status == "error":
                        continue
                    # truncated → 末尾再同期 (new_pos=size) / ok → 進行 / nochange → 据置
                    state[sid] = (path, new_pos)
                    if status == "ok" and lines:
                        last_line_at[sid] = time.monotonic()
                    # idle watchdog: busy のまま長時間 静かなら file 真値で再判定 (= 終端マーカー
                    # 欠落 / 取りこぼしのバックストップ)。 user_stopped 中は触らない。
                    st_w = stream_states.get(sid)
                    if (
                        st_w is not None and st_w.busy and not st_w.user_stopped
                        and time.monotonic() - last_line_at.get(sid, time.monotonic()) >= WATCHDOG_IDLE_SEC
                        and not _busy_after_idle(path)
                    ):
                        st_w.busy = False
                        last_line_at[sid] = time.monotonic()  # 再発火を抑える
                        sessions_overview.notify()
                    # back-off 更新: next_interval helper (= backend-F-42) に集約。
                    # **busy=true 中の sid は back-off せず即時 poll**: end_turn 到着時の
                    # busy=false 遷移を 2s 遅延させない (= 「応答来たのに停止ボタンのまま」 抑止)。
                    is_busy = st_w is not None and st_w.busy and not st_w.user_stopped
                    made_progress = (status == "ok" and bool(lines)) or is_busy
                    sid_interval[sid] = next_interval(
                        sid_interval.get(sid, POLL_INTERVAL), made_progress
                    )
                    next_poll_at[sid] = now_mono + sid_interval[sid]
                    if status != "ok":
                        continue
                    for raw in lines:
                        raw = raw.strip()
                        if not raw:
                            continue
                        try:
                            obj = json.loads(raw)
                        except json.JSONDecodeError:
                            continue
                        _maybe_push_blockers(sid, obj)
                        _update_busy(sid, obj)
                        # agent_status (= current_tool / todos / pending_question /
                        # pending_plan / model / ctx_pct) も backend 側で常時更新する。
                        # SSE 接続中の session しか更新されないと、 非アクティブタブの
                        # AskUserQuestion / ExitPlanMode が overview SSE の pending_*
                        # フラグに反映されない (= hook 経路だけが頼り)。 idempotent + 二重発火
                        # gate 済みなので SSE 経路と並走しても害なし。
                        if _mutate_agent_status(sid, obj):
                            st_obj = stream_states.get(sid)
                            if st_obj is not None:
                                st_obj.status_event.set()
                                sessions_overview.notify()  # 全 sid SSE にも伝播
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("monitor_all_sessions_loop iteration failed")
    except asyncio.CancelledError:
        logger.info("monitor_all_sessions_loop cancelled")
        raise
