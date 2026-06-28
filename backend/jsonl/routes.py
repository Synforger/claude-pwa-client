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
from dataclasses import dataclass, field
from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse

from backend.jsonl.events import jsonl_line_to_events
from backend.observability.correlation import current_corr_id
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
from backend.state import (
    ALL_SUBSCRIBER_KEY,
    agent_status,
    jsonl_event_broadcaster,
    sessions_overview,
    stream_states,
)


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


def _inject_envelope(event: dict, sid: str) -> dict:
    """SSE 配信前に sid + corr_id を必ず付与する (= contracts/schema/sse-events.yaml の global required、 ADR-012)。

    既に event 側で sid / corr_id が入ってれば尊重 (= 上流 (= monitor の publish) が adopted
    した値が消えない)。 frontend は全 event でこの 2 field を前提に dispatch する。
    """
    event.setdefault("sid", sid)
    event.setdefault("corr_id", current_corr_id())
    return event


def _lines_to_sse(lines: list[str], pos: int, session_id: str) -> list[str]:
    """JSONL 行 (文字列) のリストを SSE フレームのリストに変換する (= **replay 専用 pure 関数**)。

    F-06: 旧版は per-line で `_track_turn_start` / `_mutate_agent_status` を呼んで
    backend state を mutate し、 monitor_all_sessions_loop と二重 driver で同じ field を
    上書きする構造だった (= dual-driver による pending_question 等の race)。 mutate 経路は
    monitor 単一に絞り (= `_process_new_lines` 内)、 SSE 配信側は jsonl_line_to_events を
    呼んで event を SSE フレームに整形するだけの pure 関数に降格する。

    duration_ms (= attach_duration_to_result) も replay 経路では呼ばない。 monitor 側で
    publish 時に inject 済 (= per-sid SSE は broadcaster Queue subscriber でその event を
    そのまま受ける)。 初回接続時の replay には duration_ms が乗らないケースが残るが、
    historic event なので表示挙動上の害は無い (= 「推論中」 表示は live 経路で消える)。

    各フレームに `id: <pos>` (= この行群を読み終えた後のバイト位置) を付ける。 EventSource は
    受信した最後の id を保持し、 再接続時に `Last-Event-ID` ヘッダで送るので、 backend は
    そこから続きだけ流せる (= backend 再起動後の全 replay を回避)。
    """
    frames: list[str] = []
    for raw in lines:
        raw = raw.strip()
        if not raw:
            continue
        try:
            obj = json.loads(raw)
        except json.JSONDecodeError:
            continue
        for event in jsonl_line_to_events(obj):
            _inject_envelope(event, session_id)
            frames.append(f"id: {pos}\ndata: {json.dumps(event, ensure_ascii=False)}\n\n")
    return frames


def _lines_to_events(lines: list[str]) -> list[dict]:
    """JSONL 行 (文字列) を event dict のリストに変換 (= broadcaster publish 用、 pure)。"""
    out: list[dict] = []
    for raw in lines:
        raw = raw.strip()
        if not raw:
            continue
        try:
            obj = json.loads(raw)
        except json.JSONDecodeError:
            continue
        out.extend(jsonl_line_to_events(obj))
    return out


def _initial_offset(path: Path) -> int:
    """thin wrapper: tail.initial_offset(path, INITIAL_REPLAY_LINES) (= backend-F-41 で移送済)。
    既存 test (test_jsonl_routes.py) との後方互換のために残す。 新規 consumer は
    `backend.jsonl.tail.initial_offset` を直接 import すること。"""
    return _initial_offset_impl(path, INITIAL_REPLAY_LINES)


async def _jsonl_sse(session_id: str, start_pos: int | None = None):
    """per-sid SSE generator: 過去 message を file から replay → 以降は broadcaster Queue
    subscriber で live event を受ける (= F-02 / F-06、 mutate は monitor 一本化)。

    既存 frontend (= 旧 endpoint 利用) は無変更で動く: replay は `?from=<offset>` の意味論
    も含めて旧来挙動を温存、 live 経路だけが「monitor が publish した event を Queue で受ける」
    pub/sub 化される (= per-tick file tail を SSE 接続ごとに重ねない)。
    """
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

    # 初回 replay (= 再接続時は start_pos 以降のみ = 差分)。 file から直接読む経路 (= monitor
    # 経路に依存しない)。
    lines, pos = _read_complete_lines(path, pos)
    for frame in _lines_to_sse(lines, pos, session_id):
        yield frame

    # live: broadcaster Queue subscriber に切替。 mutator / publish は monitor 単一経路。
    queue = jsonl_event_broadcaster.subscribe(session_id)
    try:
        while True:
            try:
                event = await asyncio.wait_for(queue.get(), timeout=_IDLE_MAX_INTERVAL)
            except asyncio.TimeoutError:
                yield ": keep-alive\n\n"
                continue
            # broadcast 経路から来る event は dict。 sid 付きの場合もあるが per-sid SSE では
            # frontend が無変更で動くよう sid field は除去せず温存 (= 旧 wire と互換、 frontend
            # は未使用 field を無視)。 SSE id は frontend が ?from=<offset> で投げ直すための
            # backend file offset と整合させたいが、 publish 経路では offset を持たないので、
            # event の lastEventId は frontend の offsetRef 連続性のため pos (= 最新 replay 末尾)
            # を維持する (= 切断 → reconnect 時の "Last-Event-ID" は pos 値)。 monitor が
            # 進めた offset は frontend が次回接続時に backend に問い直す必要は無く、 replay 経路の
            # `?from=<offset>` で旧来通り差分のみ取れる。
            _inject_envelope(event, session_id)
            yield f"id: {pos}\ndata: {json.dumps(event, ensure_ascii=False)}\n\n"
    finally:
        jsonl_event_broadcaster.unsubscribe(session_id, queue)


@router.get("/jsonl/_debug/bindings")
async def jsonl_debug_bindings() -> dict:
    """debug: 現在 backend mem に持ってる watcher binding 一覧。"""
    import backend.jsonl.watcher as jsonl_watcher
    return jsonl_watcher.list_bindings()


def _parse_all_from(spec: str | None) -> dict[str, int]:
    """`from=sid1:offset1,sid2:offset2,...` を {sid: offset} に parse する (= F-15)。

    空 / None / 不正フォーマットは {} (= 各 sid 初回扱いで `_initial_offset` を使う)。
    sid に ':' / ',' は含まれない (= ses_<hex>) のでシンプルな split で良い。 offset の
    int 変換失敗は当該 sid を skip (= 0 ではなく省略、 caller が初回 fallback する)。
    """
    if not spec:
        return {}
    out: dict[str, int] = {}
    for entry in spec.split(","):
        entry = entry.strip()
        if not entry or ":" not in entry:
            continue
        sid, _, off = entry.rpartition(":")
        sid = sid.strip()
        if not sid:
            continue
        try:
            out[sid] = int(off)
        except (ValueError, TypeError):
            continue
    return out


async def _jsonl_sse_all(start_pos_map: dict[str, int]):
    """全 sid を 1 接続で配信する SSE (= F-15)。

    接続時に各 sid の `from` offset から file replay → broadcaster.subscribe("all") で
    全 sid の live event を Queue 経由で受ける。 frontend は本 endpoint 1 本で activeSid
    含む全 sid event を受信し、 sid 別 offset map を localStorage 永続化する (= タブ切替
    1-3s 待ち解消、 W2-A の Map 化 useStreamBuffer と整合)。

    event は `{..., "sid": <sid>}` 形式で送る (= monitor 経路で publish 時に sid を埋め込み済)。
    SSE id は `<sid>:<pos>` 形式で送り、 EventSource の Last-Event-ID 経由再接続では
    `?from=<sid>:<pos>,<sid>:<pos>,...` を frontend が組み直して再投入する規約 (= EventSource
    の単純な Last-Event-ID では sid 別 offset map を表現できないので、 frontend は onmessage
    内で lastEventId を parse して offsetRef に格納する)。
    """
    from backend.state import sessions_meta as _sm
    from backend.terminal.routes import ensure_pty_session_for

    # 1) 各 sid を起動 (= 既存挙動と互換、 per-sid SSE と同じ)。 失敗しても他 sid を続行。
    for sid in list(_sm.keys()):
        try:
            await ensure_pty_session_for(sid)
        except Exception:
            pass

    # 2) 各 sid の file replay (= 接続時に過去 N 行を吐く)。
    #    replay pos は per-sid に {sid: pos} で track して event の id に乗せる。
    replay_pos: dict[str, int] = {}
    for sid in list(_sm.keys()):
        path = _latest_jsonl(sid)
        if path is None:
            continue
        try:
            size = path.stat().st_size
        except OSError:
            continue
        start = start_pos_map.get(sid)
        if start is not None and 0 <= start <= size:
            pos = start
        else:
            pos = _initial_offset(path)
        lines, new_pos = _read_complete_lines(path, pos)
        replay_pos[sid] = new_pos
        for event in _lines_to_events(lines):
            _inject_envelope(event, sid)
            yield f"id: {sid}:{new_pos}\ndata: {json.dumps(event, ensure_ascii=False)}\n\n"

    # 3) live: broadcaster "all" subscriber に切替。
    queue = jsonl_event_broadcaster.subscribe(ALL_SUBSCRIBER_KEY)
    try:
        while True:
            try:
                event = await asyncio.wait_for(queue.get(), timeout=_IDLE_MAX_INTERVAL)
            except asyncio.TimeoutError:
                yield ": keep-alive\n\n"
                continue
            sid = event.get("sid") or ""
            # live event の SSE id には replay 末尾 pos を踏襲 (= 厳密 byte offset 整合は
            # 維持できないが、 frontend は最終的に file replay で同期し直す形)。
            pos = replay_pos.get(sid, 0)
            _inject_envelope(event, sid)
            yield f"id: {sid}:{pos}\ndata: {json.dumps(event, ensure_ascii=False)}\n\n"
    finally:
        jsonl_event_broadcaster.unsubscribe(ALL_SUBSCRIBER_KEY, queue)


@router.get("/jsonl/stream/all")
async def jsonl_stream_all(request: Request):
    """全 sid の jsonl event を 1 SSE で配信する (= F-15)。

    query: `?from=<sid>:<off>,<sid>:<off>,...` で per-sid offset を渡す。 EventSource の
    自動再接続は Last-Event-ID (= 単一文字列) なので、 frontend 側で `<sid>:<pos>` の
    最新 1 件しか戻ってこない。 sid 別 offset map の精度維持は frontend onmessage 内で
    都度 localStorage に書く運用とする (= EventSource header 経路は単一 sid 分しか保持
    できないので、 接続時 query 構築は frontend 側 offsetRef を真値として行う)。
    """
    src = request.query_params.get("from")
    # Last-Event-ID も拾うが単一値しか入らないので参考扱い (= ?from が主)。
    last_eid = request.headers.get("last-event-id")
    start_map = _parse_all_from(src)
    if not start_map and last_eid:
        # 単一 `<sid>:<pos>` だけが入っていれば 1 sid 分だけ復元 (= safety net、 frontend が
        # ?from を組めなかった retry 経路の保険)。
        start_map = _parse_all_from(last_eid)
    return StreamingResponse(
        _jsonl_sse_all(start_map),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


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
# backend の lifespan task として全 PWA session の JSONL を tail し、 AskUserQuestion
# 発火 / stop_reason 異常を検出して Web Push を飛ばす。 SSE 経路 (= /jsonl/stream) の
# _maybe_push_blockers 呼び出しは廃止済 (= 二重発火回避)。

# F-65: 1 sid の per-tick 処理で連続して例外が出た時に一時的に poll をスキップさせる
# (= 該当 sid の JSONL が壊れてる等で毎 tick 同じ例外を吐き続けるのを抑制)。 N 回連続
# 失敗で QUARANTINE_SEC 静かにする → 復帰したら counter を 0 に戻す。 backend 全体を
# 落とさず poison 1 sid だけ隔離する設計。
_QUARANTINE_THRESHOLD = 5
_QUARANTINE_SEC = 30.0


@dataclass
class SessionTailState:
    """1 sid 分の monitor 状態を集約する dataclass (= backend-F-03)。

    旧 `monitor_all_sessions_loop` は 5 つの per-sid dict (= state / last_line_at /
    sid_interval / next_poll_at + failure counter) を並走させて 397 行の inner ループに
    展開していた。 1 sid あたり 1 instance にまとめて method 呼び出し可能にすることで、
    SessionTailer pattern を最小コストで導入する。 既存挙動は完全互換。
    """
    path: Path | None = None
    offset: int = 0
    last_line_at: float = field(default_factory=time.monotonic)
    interval: float = POLL_INTERVAL
    next_poll_at: float = 0.0
    # F-65: 連続失敗 counter。 _QUARANTINE_THRESHOLD で QUARANTINE_SEC 沈黙
    consecutive_failures: int = 0


def _reset_jsonl_session_metadata(sid: str) -> None:
    """path 切替時 (= /clear / resume / フォーク等で claude session が入れ替わった時)
    の蓄積メタ reset。 PR / task list が前 session から持ち越されないようにする
    (2026-06-12)。"""
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


def _initialize_sid_tail(sid: str, tstate: SessionTailState, path: Path) -> None:
    """初回 or path 切替時の末尾再同期。 過去行を再通知しないよう offset = 現 size に
    置き、 末尾から現在値で busy を 1 回算出する (= backend 起動時に推論中だった session
    も正しく busy=True にする)。"""
    prev_path = tstate.path
    try:
        tstate.offset = path.stat().st_size
    except OSError:
        return
    tstate.path = path
    if prev_path is not None and prev_path != path:
        _reset_jsonl_session_metadata(sid)
    st = stream_states.get(sid)
    if st is not None:
        new_busy = _compute_busy_from_tail(path)
        if st.user_stopped:
            new_busy = False
        if new_busy != st.busy:
            st.busy = new_busy
            sessions_overview.notify()
    tstate.last_line_at = time.monotonic()


def _process_new_lines(sid: str, lines: list[str]) -> None:
    """tail で取れた新規完全行を 1 sid 分処理する。 旧 inner loop の per-line 部分を
    切り出した pure-ish function。 mutate / push 発火 + broadcaster へ event publish を行う。

    F-02 / F-06: 旧版は mutate のみ。 SSE 側 (`_lines_to_sse`) も独自に mutate していて
    dual-driver な race を抱えていた。 本関数を**単一経路**として event 生成 + mutator +
    publish を担い、 SSE 配信側は broadcaster Queue subscriber に降格する。
    """
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
        _track_turn_start(sid, obj)
        # agent_status (= current_tool / todos / pending_question / pending_plan /
        # model / ctx_pct) も backend 側で常時更新する。 SSE 接続中の session しか
        # 更新されないと、 非アクティブタブの AskUserQuestion / ExitPlanMode が
        # overview SSE の pending_* フラグに反映されない (= hook 経路だけが頼り)。
        # idempotent + 二重発火 gate 済なので SSE 経路と並走しても害なし。
        if _mutate_agent_status(sid, obj):
            st_obj = stream_states.get(sid)
            if st_obj is not None:
                st_obj.status_event.set()
                sessions_overview.notify()  # 全 sid SSE にも伝播
        # F-02 / F-06: monitor 経路で event を生成 + broadcaster publish。 SSE 配信側は
        # この event を Queue で受けるだけ (= 旧 per-SSE 接続 tail を集約)。
        evts = jsonl_line_to_events(obj)
        _attach_duration_to_result(sid, obj, evts)
        for event in evts:
            # /all subscriber が sid 別に振り分けられるよう event dict に sid を埋める。
            # frontend は per-sid SSE では未使用、 /all SSE で activeSid 含む全 sid 更新の
            # 振分に使う。 event 自身に sid field が予めある場合は尊重 (= 滅多にない)。
            event.setdefault("sid", sid)
            jsonl_event_broadcaster.publish(sid, event)


def _tick_sid(sid: str, tstate: SessionTailState, now_mono: float) -> None:
    """1 sid 分の per-tick 処理 (= 旧 inner loop body)。 F-65 quarantine 経路では本関数を
    例外で抜け、 caller の monitor_all_sessions_loop で counter を increment する。"""
    path = _latest_jsonl(sid)
    if path is None:
        tstate.next_poll_at = now_mono + POLL_INTERVAL
        return
    if tstate.path is None or tstate.path != path:
        _initialize_sid_tail(sid, tstate, path)
        return
    lines, new_pos, status = _read_tail(path, tstate.offset)
    if status == "error":
        return
    tstate.offset = new_pos
    if status == "ok" and lines:
        tstate.last_line_at = time.monotonic()
    # Task 実行中の subagent 進捗を追う (= 旧 per-sid SSE で per-tick 呼ばれていたのを
    # F-06 で monitor 単一経路に集約。 SSE は broadcaster Queue 経由で受ける)。
    subagent_changed = _refresh_subagent_status(sid, path)
    if subagent_changed:
        st_sub = stream_states.get(sid)
        if st_sub is not None:
            st_sub.status_event.set()
            sessions_overview.notify()
    # idle watchdog: busy のまま長時間 静かなら file 真値で再判定 (= 終端マーカー欠落 /
    # 取りこぼしのバックストップ)。 user_stopped 中は触らない。
    st_w = stream_states.get(sid)
    if (
        st_w is not None and st_w.busy and not st_w.user_stopped
        and time.monotonic() - tstate.last_line_at >= WATCHDOG_IDLE_SEC
        and not _busy_after_idle(path)
    ):
        st_w.busy = False
        tstate.last_line_at = time.monotonic()  # 再発火を抑える
        sessions_overview.notify()
    # back-off 更新: next_interval helper (= backend-F-42) に集約。 busy=true 中の sid
    # は back-off せず即時 poll (= end_turn 到着時の busy=false 遷移を 2s 遅延させない)。
    is_busy = st_w is not None and st_w.busy and not st_w.user_stopped
    made_progress = (status == "ok" and bool(lines)) or is_busy
    tstate.interval = next_interval(tstate.interval, made_progress)
    tstate.next_poll_at = now_mono + tstate.interval
    if status != "ok":
        return
    _process_new_lines(sid, lines)


# F-01: 信号源 (= watchfiles の awatch から得た「変更があった jsonl path」 set)。
# monitor が awatch task を別途回し、 信号で next_poll_at を即時 advance させる
# (= 既存 polling と並走する fallback 設計、 watchfiles 起動失敗時も 0.5s polling で
# 自己回復する安全側の設計)。
_watch_signal_paths: set[Path] = set()
_watch_signal_lock: asyncio.Lock | None = None


def _get_watch_signal_lock() -> asyncio.Lock:
    """awatch task と monitor の signal 共有 lock を遅延生成 (= test の event loop
    隔離保護)。"""
    global _watch_signal_lock
    if _watch_signal_lock is None:
        _watch_signal_lock = asyncio.Lock()
    return _watch_signal_lock


async def _watch_jsonl_paths_loop():
    """watchfiles で全 sid の jsonl_path 親 dir 群を監視し、 変更があった path を
    `_watch_signal_paths` に積む (= backend-F-01 / F-16)。 monitor がこれを per-tick
    で吸い出して next_poll_at[sid] を即時 advance する。

    watchfiles 未到達の path (= claude が path 解決前) は次の per-sid initialize で
    polling 経路が拾うので、 awatch failure は致命的でない。 例外時は loop を再起動。
    """
    try:
        from watchfiles import awatch  # noqa: PLC0415
    except ImportError:
        logger.warning("watchfiles unavailable; falling back to pure polling")
        return
    logger.info("_watch_jsonl_paths_loop started (watchfiles driver)")
    while True:
        try:
            # 監視対象 dir 群 (= 全 sid の jsonl 親 dir)。 sid 追加 / path 切替で随時
            # 変わるので、 awatch を「現存 path 群」 で起動し、 path 変動時は loop を
            # 短く回して再起動する。
            from backend.state import sessions_meta as _sm  # noqa: PLC0415
            dirs: set[Path] = set()
            for sid in list(_sm.keys()):
                p = _latest_jsonl(sid)
                if p is not None:
                    dirs.add(p.parent)
            if not dirs:
                await asyncio.sleep(POLL_INTERVAL)
                continue
            # awatch は内部で 100ms polling (= macOS fsevents ベース) なので一般に体感
            # 即時。 step=100ms 指定で wake up を加速。
            async for changes in awatch(*dirs, step=100, recursive=False):
                lock = _get_watch_signal_lock()
                async with lock:
                    for _evt_type, raw_path in changes:
                        _watch_signal_paths.add(Path(raw_path))
                # 既存 dirs に追加 sid が出てきたら awatch を再起動する必要があるため、
                # 一定間隔で外側 while に戻して dirs を再評価する。 5 回 change 受けたら
                # break。 信号は while 外でも吸われるので取りこぼし無し。
                if len(_watch_signal_paths) > 50:
                    break
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("_watch_jsonl_paths_loop iteration failed; retrying")
            await asyncio.sleep(1.0)


def _drain_watch_signals_to_state(states: dict[str, SessionTailState], sid_by_path: dict[Path, str]) -> None:
    """awatch の信号 set から「changed sid」 を解決して next_poll_at を即時 advance
    する。 watchfiles が拾った change から数 ms で monitor が tail に進む経路 (= F-01)。"""
    if not _watch_signal_paths:
        return
    # asyncio.Lock を sync で取得しないために集合を交換する手法 (= GIL で原子的に空 set
    # と差し替え) を取る。 take は別の参照、 _watch_signal_paths はクリアされる。
    take = _watch_signal_paths.copy()
    _watch_signal_paths.clear()
    now_mono = time.monotonic()
    for p in take:
        sid = sid_by_path.get(p)
        if sid is None:
            continue
        ts = states.get(sid)
        if ts is not None:
            ts.next_poll_at = now_mono  # 次 tick 即発火


async def monitor_all_sessions_loop():
    """全 PWA session の JSONL を常時 tail し、 推論を止める要因を検出して push 発火する。

    起動時は各 sid を末尾 offset から開始する (= backend 起動前の過去行は通知しない)。
    `/clear` 等で claude_sid が切り替わると `_latest_jsonl` が新 path を返すので、
    そのときは新 path の末尾から再同期する。 file が縮んだ (rotate / truncate) 場合も同様。

    内部 state: states[sid] = SessionTailState (= path / offset / last_line_at /
    interval / next_poll_at / consecutive_failures、 backend-F-03 で集約)。 SSE 経路の
    `offsetRef` とは独立した backend 内追跡 (= frontend の localStorage が消えても影響
    無し)。 F-65: per-sid 連続失敗 counter で poison 1 sid を一時 quarantine する。
    F-01: watchfiles awatch task を別途起動し、 信号で next_poll_at を advance する。
    """
    states: dict[str, SessionTailState] = {}
    logger.info("monitor_all_sessions_loop started")
    # F-01: watchfiles 駆動の wake-up task を並走 (= fallback として polling は維持)。
    watcher_task = asyncio.create_task(_watch_jsonl_paths_loop())
    try:
        while True:
            try:
                await asyncio.sleep(POLL_INTERVAL)
                from backend.state import sessions_meta as _sessions_meta  # 動的参照
                # 削除済み session の追跡 entry を刈り取る (= 無停止運用での単調増加防止)
                for stale in [s for s in states if s not in _sessions_meta]:
                    states.pop(stale, None)
                # F-01: watchfiles の信号を吸い出して next_poll_at を advance する。
                sid_by_path: dict[Path, str] = {}
                for sid, ts in states.items():
                    if ts.path is not None:
                        sid_by_path[ts.path] = sid
                _drain_watch_signals_to_state(states, sid_by_path)
                now_mono = time.monotonic()
                for sid in list(_sessions_meta.keys()):
                    tstate = states.get(sid)
                    if tstate is None:
                        tstate = SessionTailState()
                        states[sid] = tstate
                    # F-65: quarantine 中なら sleep 中扱いで skip
                    if tstate.next_poll_at > now_mono:
                        continue
                    try:
                        _tick_sid(sid, tstate, now_mono)
                        # 成功 (= 例外無し) → failure counter を 0 へ
                        if tstate.consecutive_failures:
                            tstate.consecutive_failures = 0
                    except Exception:
                        # F-65: 1 sid 分の per-tick で例外発生 → counter increment、
                        # 閾値到達で quarantine。 backend 全体は落とさず poison 1 sid だけ
                        # 隔離する。
                        tstate.consecutive_failures += 1
                        if tstate.consecutive_failures >= _QUARANTINE_THRESHOLD:
                            tstate.next_poll_at = now_mono + _QUARANTINE_SEC
                            tstate.interval = POLL_INTERVAL
                            logger.exception(
                                "monitor: sid=%s quarantined for %.0fs after %d consecutive failures",
                                sid, _QUARANTINE_SEC, tstate.consecutive_failures,
                            )
                        else:
                            logger.exception(
                                "monitor: sid=%s tick failed (count=%d)",
                                sid, tstate.consecutive_failures,
                            )
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("monitor_all_sessions_loop outer iteration failed")
    except asyncio.CancelledError:
        logger.info("monitor_all_sessions_loop cancelled")
        watcher_task.cancel()
        try:
            await watcher_task
        except (asyncio.CancelledError, Exception):
            pass
        raise
