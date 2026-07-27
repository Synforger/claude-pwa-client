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

from fastapi import APIRouter, Query, Request
from fastapi.responses import StreamingResponse

from backend.jsonl.events import jsonl_line_to_events
from backend.terminal.send_dedup import send_dedup
from backend.observability.correlation import current_corr_id
from backend.observability.metrics import metrics
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
from backend.core.jsonl_tail import (
    initial_offset as _initial_offset_impl,
    read_complete_lines as _read_complete_lines,
    read_tail_with_pos as _read_tail_with_pos,
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

# idle 時の back-off 上限秒 (= monitor の polling 上限。 新着検知の最悪遅延を決める)。
_IDLE_MAX_INTERVAL = 2.0
# back-off の伸び率 (= 変化なし時、 current * GROWTH で次回間隔を伸ばす)。
_IDLE_GROWTH = 1.5
# SSE keep-alive 送出間隔秒。 monitor back-off とは責務が別 (= こちらは接続維持の心拍のみ)。
def next_interval(current: float, made_progress: bool) -> float:
    """idle back-off helper (= backend-F-42)。 push 監視
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
    `backend.core.jsonl_tail.initial_offset` を直接 import すること。"""
    return _initial_offset_impl(path, INITIAL_REPLAY_LINES)


# 履歴 GET で返す tool_result 本文の上限 (= 2026-07-27 体感速度)。
#
# UI がツール結果を表示するのは冒頭 800 文字だけ (= MessageItem.RESULT_PREVIEW_CHARS、 以降は
# 「省略」 表記)。 一方 JSONL の tool_result は巨大ファイル読み / 長い command 出力で 1 件
# 数百 KB になり、 実測では履歴 1.2MB のうち **65% (812KB) が tool_result** だった。 表示に
# 使われない本文を携帯まで運ぶのは純粋な待ち時間なので、 履歴経路に限って切り詰める。
#
# 800 でなく 2000 なのは余裕。 formatToolResultContent が list → text 連結する際に長さが
# ずれるので、 表示上限より広く取って「表示は full と同一」 を担保する。
# **ライブ SSE は対象外** (= 進行中の tool 出力は完全な形で届く。 切り詰めは「もう画面外の
# 過去ログを読み直す時」 だけの最適化)。 元の文字数は full_chars で残すので、 UI の文字数
# 表示は truncate 後も正確なまま。
TOOL_RESULT_PREVIEW_CHARS = 2000


def _shrink_tool_results(ev: dict) -> None:
    """履歴 event 内の巨大な tool_result 本文を preview に置き換える (= in-place)。

    対象は type=user の message.content にある tool_result ブロックのみ。 content は string /
    block list の両形があるので双方を扱う。 切り詰めた場合だけ `full_chars` (= 元の文字数) を
    足すので、 受け手は「有れば truncate 済」 と判定できる。
    """
    if ev.get("type") != "user":
        return
    content = (ev.get("message") or {}).get("content")
    if not isinstance(content, list):
        return
    for block in content:
        if not isinstance(block, dict) or block.get("type") != "tool_result":
            continue
        body = block.get("content")
        if isinstance(body, str):
            if len(body) > TOOL_RESULT_PREVIEW_CHARS:
                block["full_chars"] = len(body)
                block["content"] = body[:TOOL_RESULT_PREVIEW_CHARS]
        elif isinstance(body, list):
            total = 0
            kept: list = []
            budget_left = TOOL_RESULT_PREVIEW_CHARS
            stripped_image = False
            for part in body:
                text = part.get("text") if isinstance(part, dict) else None
                if not isinstance(text, str):
                    # image ブロックは **本体 (= base64) を落とす**。 UI は tool_result 内の画像を
                    # 実データとして描画せず「画像」 プレースホルダ 1 語に畳む
                    # (= utils/format.js formatToolResultContent の `type === 'image'` 経路) ので、
                    # base64 は 1 byte も表示に使われない。 実測では 1 件 384KB のスクショが
                    # 履歴に丸ごと乗っていた。 type は残すのでプレースホルダ表示は不変。
                    if isinstance(part, dict) and part.get("type") == "image":
                        kept.append({"type": "image"})
                        stripped_image = True
                        continue
                    kept.append(part)  # それ以外の未知ブロックはそのまま残す
                    continue
                total += len(text)
                if budget_left <= 0:
                    continue
                if len(text) > budget_left:
                    kept.append({**part, "text": text[:budget_left]})
                    budget_left = 0
                else:
                    kept.append(part)
                    budget_left -= len(text)
            # text が溢れた時だけ full_chars を足す (= 文字数ラベルの真値)。 画像を落とした
            # だけの時は文字数が変わらないので full_chars は付けず、 content の差し替えのみ。
            if total > TOOL_RESULT_PREVIEW_CHARS:
                block["full_chars"] = total
                block["content"] = kept
            elif stripped_image:
                block["content"] = kept


@router.get("/jsonl/history/{session_id}")
def get_chat_history(
    session_id: str,
    from_pos: int | None = Query(None, alias="from"),
) -> dict:
    """チャット履歴の権威スナップショットを 1 発 GET で返す (= client=射影の「状態は GET」 経路)。

    frontend は sid 表示時にこれを叩いて履歴を確定させ (= stream の初回 replay 依存を外す)、
    以降 stream は差分だけを流す。 events は SSE の ev payload と同形状、 pos は読み終えた
    byte 位置 (= stream 購読の起点にすれば replay 重複が消える)。 from (= 描画・永続化した
    offset) 指定ありはその位置以降、 未指定/無効 (= 初回 / cache 消失) は直近 N 行。 GET は
    stream とは別リクエストなので、 stream が復帰し損ねても履歴は必ず取れる。
    """
    path = _latest_jsonl(session_id)
    if path is None:
        return {"events": [], "pos": 0}
    try:
        size = path.stat().st_size
    except OSError:
        size = 0
    if from_pos is not None and 0 <= from_pos <= size:
        pos = from_pos
    else:
        pos = _initial_offset(path)
    lines, end_pos = _read_complete_lines(path, pos)
    events = _lines_to_events(lines)
    for ev in events:
        _inject_envelope(ev, session_id)
        _shrink_tool_results(ev)
    return {"events": events, "pos": end_pos}


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
    """初回 or path 切替時の path 取付。 旧版は `offset = path.stat().st_size` で path
    切替前に書かれていた全行を skip する設計だったが、 path 切替検知が monitor の次 tick
    待ちのため、 その窓に claude が boot banner + user 初発 + tool_use/tool_result +
    assistant final を一気に書き終えるケースで全部巻き添え skip され、 「結果が来るまで
    chat に何も表示されない、 来た瞬間にまとめて batch 表示」 という reproducible な
    UX 退行になっていた (= 2026-06-30 真因確定、 PR #37 で塞いだ EventSource reconnect
    経路とは別の root cause)。

    新設計 = path 切替時は **offset=0** から読む。 chat 非表示対象 (= isMeta /
    isSidechain / system init / queue-operation 等) は `backend/jsonl/events.py`
    `jsonl_line_to_events` の filter で event 化されないので chat に漏れない。 fork
    で lineage 複製された新 jsonl の過去行や backend restart 後の全 jsonl も live で
    publish されるが、 frontend dedup (= user は `reconcileUserMessage` の uuid 一致
    全長 dedup、 agent は `useStreamBuffer.findRecentByUuid` を Map<uuid,index> 全長
    lookup 化) で重複表示なし。"""
    prev_path = tstate.path
    if not path.exists():
        return
    tstate.offset = 0
    tstate.path = path
    if prev_path is not None and prev_path != path:
        _reset_jsonl_session_metadata(sid)
    st = stream_states.get(sid)
    if st is not None:
        # path 切替 (= restart / fork) は別 claude session。 旧 path の queue は無効なのでクリア
        # してから新 path の末尾で busy を再計算する (= 古い queue を新 session に持ち込まない)。
        st.queued_sends = 0
        new_busy = _compute_busy_from_tail(path)
        if st.user_stopped:
            new_busy = False
        if new_busy != st.busy:
            st.busy = new_busy
            sessions_overview.notify()
    tstate.last_line_at = time.monotonic()


# restart / fork 経由で claude session が入れ替わる時に monitor 側の tstate を初回
# bind 扱いに戻すためのシグナル。 endpoint 側から sid を add すると、 monitor loop が
# 次 tick 開始時に当該 sid の tstate を pop して新規初期化 (= prev_path is None 経路)
# する。 endpoint と monitor の event loop は同一だが lock-free で安全 (= add は set
# 操作、 monitor は pop で取り出して即 clear)。
_sid_tail_reset_pending: set[str] = set()


def request_sid_tail_reset(sid: str) -> None:
    """restart_session / fork_session 等の endpoint から呼ぶ。 次の monitor tick で
    当該 sid の SessionTailState を破棄して初回 bind と同じ経路 (= offset=0 から path
    内全行 publish) を踏ませる。 stream-from-zero 設計の入口 (= 2026-06-30)。"""
    _sid_tail_reset_pending.add(sid)


def _process_new_lines(sid: str, lines_with_pos: list[tuple[str, int]]) -> None:
    """tail で取れた新規完全行を 1 sid 分処理する。 旧 inner loop の per-line 部分を
    切り出した pure-ish function。 mutate / push 発火 + broadcaster へ event publish を行う。

    F-02 / F-06: 旧版は mutate のみ。 SSE 側 (`_lines_to_sse`) も独自に mutate していて
    dual-driver な race を抱えていた。 本関数を**単一経路**として event 生成 + mutator +
    publish を担い、 SSE 配信側は broadcaster Queue subscriber に降格する。

    各行はその行を読み終えた実 byte 位置 (= line_pos) とペアで受け、 publish に載せる。
    SSE 配信側はこれを id 行に使い、 live 中も client の offset が前進する (= 再接続時の
    replay を差分だけに保つ)。
    """
    for raw, line_pos in lines_with_pos:
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
        # agent_status (= current_tool / todos / pending_plan /
        # model / ctx_pct) も backend 側で常時更新する。 SSE 接続中の session しか
        # 更新されないと、 非アクティブタブの AskUserQuestion / ExitPlanMode が
        # overview SSE の pending_* フラグに反映されない (= hook 経路だけが頼り)。
        # idempotent + 二重発火 gate 済なので SSE 経路と並走しても害なし。
        mutated = _mutate_agent_status(sid, obj)
        metrics.inc("monitor.mutated" if mutated else "monitor.mutate_noop")
        if mutated:
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
            # user_message event に client 発行 send_id を焼く。 その sid で「未 mapping
            # 最古 send_id」 に本 JSONL uuid を対応付け、 同 send_id を event に載せる
            # (= 楽観 bubble ↔ 実 bubble の厳密対応付け、 frontend の reconcile が
            # 優先順位で pop する identity 経路)。 対応候補が無ければ send_id なし = null
            # で流れる (frontend は近傍 optimistic pop の fallback に降格)。
            if event.get("type") == "user_message":
                jsonl_uuid = event.get("uuid")
                if jsonl_uuid:
                    bound = send_dedup.bind_jsonl_uuid(sid, jsonl_uuid)
                    if bound is not None:
                        event["send_id"] = bound
            jsonl_event_broadcaster.publish(sid, event, line_pos)


def _tick_sid(sid: str, tstate: SessionTailState, now_mono: float) -> None:
    """1 sid 分の per-tick 処理 (= 旧 inner loop body)。 F-65 quarantine 経路では本関数を
    例外で抜け、 caller の monitor_all_sessions_loop で counter を increment する。"""
    metrics.inc("monitor.ticks")
    path = _latest_jsonl(sid)
    if path is None:
        metrics.inc("monitor.no_path")
        tstate.next_poll_at = now_mono + POLL_INTERVAL
        return
    if tstate.path is None or tstate.path != path:
        metrics.inc("monitor.init_bind")
        _initialize_sid_tail(sid, tstate, path)
        return
    lines, new_pos, status = _read_tail_with_pos(path, tstate.offset)
    if status == "error":
        metrics.inc("monitor.read_error")
        return
    if lines:
        metrics.inc("monitor.lines", len(lines))
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
        st_w.queued_sends = 0  # 長時間静か = queue も含めて全消化 or 取りこぼし、 張り付き防止
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
                # restart / fork 経由の reset 要求を吸い出す (= 2026-06-30 stream-from-zero
                # 設計、 当該 sid を states から落とすと次の `_tick_sid` で `prev_path is
                # None` 経路に入り `_initialize_sid_tail` が offset=0 から読む)。
                if _sid_tail_reset_pending:
                    drained = list(_sid_tail_reset_pending)
                    _sid_tail_reset_pending.clear()
                    for sid in drained:
                        states.pop(sid, None)
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
            # benign: shutdown path — `raise` below re-raises the original CancelledError,
            # so any leftover exception from the watcher coroutine teardown is silenced.
            pass
        raise
