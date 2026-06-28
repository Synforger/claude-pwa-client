"""JSONL 1 行から session の状態 (= busy / turn 開始 / agent_status / subagent) を更新する。

`jsonl_routes._lines_to_sse` (= SSE 配信) と `monitor_all_sessions_loop` (= 全 session
push 監視) の双方から呼ばれる「JSONL → backend state mutation」 を集約する場所。

主な責務:
- busy 判定 (StreamState.busy、 backend 権威 / overview SSE 経由で frontend loading を駆動)
- turn 開始時刻 (= duration_ms 算出のため)
- agent_status の todos / plan_mode / current_tool / ctx_pct / model / pending_plan /
  pending_question の更新
- subagent の last_tool 表示 (= Task 実行中の inline 進捗)
"""
from __future__ import annotations

import asyncio
import json
import time
from collections import OrderedDict
from enum import Enum
from pathlib import Path

from backend.jsonl.events import INTERRUPT_USER_RE
from backend.jsonl.plan_choices import capture_plan_choices
from backend.jsonl.predicates import is_user_prompt as _is_user_prompt_pred
from backend.jsonl.tail import parse_jsonl_timestamp
from backend.state import agent_status, sessions_overview, stream_states
from backend.core.usage import compute_ctx_pct, format_model_name


# --- busy 判定の共通分類器 (= backend-F-04) -----------------------------------
# 旧版は `update_busy` (= 進行更新) / `compute_busy_from_tail` (= 末尾再計算) /
# `busy_after_idle` (= idle watchdog) が 1 行 → 状態の分岐を**それぞれの場所で
# 自前に書いて**いた (= stop_reason 文字列の比較が 3 箇所、 user 行判定経路も 3 箇所、
# tool_use / 中断 marker の扱いが微妙にズレていた)。 1 行 dict → Enum の純粋関数 1 本に
# 集約することで「busy 遷移ルール」 を 1 箇所で表現する。
class LineKind(Enum):
    """JSONL 1 行を busy 判定の観点で分類した kind。"""
    START = "start"              # 素ユーザ発話 (= turn 開始) — busy=True
    END = "end"                  # assistant の確定 stop_reason (!= tool_use) — busy=False
    IN_PROGRESS = "in_progress"  # assistant の stop_reason == "tool_use" — busy=True
    INTERRUPT = "interrupt"      # `[Request interrupted by user]` marker — busy=False (= 中断完了)
    OTHER = "other"              # 上記いずれでもない (= mode / attachment / tool_result 等)


def classify_jsonl_line(line: dict) -> LineKind:
    """JSONL 1 行を busy 観点で分類する純粋関数 (= backend-F-04)。

    分類規則:
    - assistant 行で stop_reason=="tool_use" → IN_PROGRESS (= ツール継続中、 busy 維持)
    - assistant 行で stop_reason が他の確定値 → END (= turn 完了、 busy=False)
    - assistant 行で stop_reason 欠落 → OTHER (= 末尾 partial の可能性、 caller が判断)
    - user 行で INTERRUPT marker 単独 → INTERRUPT (= 中断完了、 busy=False)
    - user 行で素プロンプト (= predicates.is_user_prompt) → START (= turn 開始)
    - その他 (sidechain / meta / tool_result / mode 等) → OTHER

    INTERRUPT を START と分離する理由: `[Request interrupted by user]` は claude が
    中断完了 marker として書くもので、 応答 stop_reason 行が来ない (2026-06-04 真因)。
    predicates.is_user_prompt は INTERRUPT を弾くので、 ここで明示的に separate kind に
    することで「中断が観測された」 という情報を caller (= busy_after_idle 等) に渡せる。
    """
    if not isinstance(line, dict):
        return LineKind.OTHER
    ltype = line.get("type")
    if ltype == "assistant":
        sr = (line.get("message") or {}).get("stop_reason")
        if sr == "tool_use":
            return LineKind.IN_PROGRESS
        if sr:
            return LineKind.END
        return LineKind.OTHER
    if ltype == "user" and not line.get("isSidechain") and not line.get("isMeta"):
        # INTERRUPT marker 単独行を検出 (= predicates.is_user_prompt は False を返す)
        content = (line.get("message") or {}).get("content")
        if isinstance(content, str):
            if INTERRUPT_USER_RE.match(content.strip()):
                return LineKind.INTERRUPT
        elif isinstance(content, list):
            # 単一 text block で INTERRUPT marker のみ ↔ それ以外の text が混ざるなら通常判定
            text_blocks = [b for b in content if isinstance(b, dict) and b.get("type") == "text"]
            if text_blocks and all(
                INTERRUPT_USER_RE.match((b.get("text") or "").strip())
                for b in text_blocks
                if (b.get("text") or "").strip()
            ) and any((b.get("text") or "").strip() for b in text_blocks):
                return LineKind.INTERRUPT
        if _is_user_prompt_pred(line):
            return LineKind.START
    return LineKind.OTHER


# sid → 直近 user 発話 (= turn 開始) の unix epoch。 stop_reason 確定行を見たら
# (現在の確定行の timestamp - 開始) を duration_ms として result event に inject する。
# プロセス内 dict なので backend 再起動で消える、 中断中の turn は duration 取得不可。
_turn_started_at: dict[str, float] = {}


# ExitPlanMode の二重起動防止用に「処理済 tool_use_id」 を sid ごとに bounded set で
# 保持する (= backend-F-14)。 旧版は a["pending_plan"]["tool_use_id"] と一致したら skip
# する gate のみで、 pending_plan が clear (= ユーザ承認 / 別 plan で上書き) された後に
# 同 tool_id が再到着 (= SSE / monitor の path 切替 race 等) すると capture を再起動して
# しまう穴があった。 OrderedDict + maxlen で「直近 64 個」 だけ覚えておく (= 過去 turn の
# 古い id は自然に押し出される、 メモリ単調増加しない)。
_PROCESSED_EXIT_PLAN_LIMIT = 64
_processed_exit_plan_ids: dict[str, OrderedDict[str, None]] = {}


def _remember_exit_plan(session_id: str, tool_use_id: str) -> bool:
    """ExitPlanMode の tool_use_id を sid ごとの bounded set に記録する。

    既に記録済なら False (= 二重到着 = capture を再起動しない)、 新規なら True を返す。
    set は OrderedDict + maxlen で実装、 古い順に押し出される。"""
    if not tool_use_id:
        return True  # id 不明は弾けないので素通し (= 旧挙動と同じ)
    seen = _processed_exit_plan_ids.setdefault(session_id, OrderedDict())
    if tool_use_id in seen:
        seen.move_to_end(tool_use_id)
        return False
    seen[tool_use_id] = None
    while len(seen) > _PROCESSED_EXIT_PLAN_LIMIT:
        seen.popitem(last=False)
    return True


def cleanup_orphan_exit_plan_ids() -> int:
    """`sessions_meta` に存在しない sid の `_processed_exit_plan_ids` entry を掃除する。

    呼び出し元 (= backend/core/maintenance.run_all_maintenance の summary に登録) は
    W1-C scope 外 path (= backend/core/*) のため別 round で結線する。 maxlen 64 で
    per-sid 上限があり、 そもそも unbounded ではないので未呼出でも実害は無い。
    """
    from backend.state import sessions_meta  # noqa: PLC0415
    stale = [sid for sid in _processed_exit_plan_ids if sid not in sessions_meta]
    for sid in stale:
        _processed_exit_plan_ids.pop(sid, None)
    return len(stale)


def cleanup_orphan_turn_starts() -> int:
    """`sessions_meta` に存在しない sid の `_turn_started_at` entry を掃除する。
    Stop / 削除等で pop されずに残った turn 開始時刻が、 プロセス無停止運用で累積する
    のを 1 日 1 回 (maintenance loop) で刈る。 削除件数を返す。"""
    from backend.state import sessions_meta  # noqa: PLC0415
    stale = [sid for sid in _turn_started_at if sid not in sessions_meta]
    for sid in stale:
        _turn_started_at.pop(sid, None)
    return len(stale)


# 旧版は本 module で `is_user_prompt` を独自実装していたが、 terminal/confirm.py の
# `_is_plain_user_prompt` と判定がズレる潜在 race があった (= backend-F-05)。 真値は
# `backend.jsonl.predicates.is_user_prompt` に集約済み、 ここは委譲する re-export。
# 旧来の `from backend.jsonl.session_status import is_user_prompt` 経路 (= routes.py /
# test) の後方互換も担保する。
is_user_prompt = _is_user_prompt_pred


def track_turn_start(session_id: str, line: dict) -> None:
    """素プロンプト (= ユーザ発言) の user 行で turn 開始時刻を記録する。"""
    if not is_user_prompt(line):
        return
    ts = parse_jsonl_timestamp(line.get("timestamp"))
    if ts is not None:
        _turn_started_at[session_id] = ts


def update_busy(session_id: str, line: dict) -> None:
    """JSONL 1 行から session の busy (= turn 進行中か) を更新する。 変化したら
    sessions_overview.notify() で /sessions/overview/stream に push させる。

    遷移ルールは `classify_jsonl_line` で集約:
    - START (= 素ユーザ発話) → busy=True + user_stopped 解除
    - END (= 確定 stop_reason 非 tool_use) → busy=False
    - IN_PROGRESS (= stop_reason=="tool_use") → busy=True 維持 (= 既に True なら無変化)
    - INTERRUPT (= `[Request interrupted by user]` marker) → busy=False
    - OTHER → 変化なし
    user_stopped (= ユーザが Stop ボタン押下) は busy=False を強制 (= 次 START で解除)。
    """
    st = stream_states.get(session_id)
    if st is None:
        return
    kind = classify_jsonl_line(line)
    new = st.busy
    if kind == LineKind.START:
        new = True
        st.user_stopped = False
    elif kind == LineKind.END or kind == LineKind.INTERRUPT:
        new = False
    elif kind == LineKind.IN_PROGRESS:
        new = True
    # OTHER は据置 (= busy 変化を起こさない)
    if st.user_stopped:
        new = False
    if new != st.busy:
        st.busy = new
        sessions_overview.notify()


def _read_tail_lines(path: Path, tail_bytes: int) -> list[dict] | None:
    """末尾 tail_bytes を読んで JSONL 行を dict 化 (= 失敗時 None)。
    compute_busy_from_tail / busy_after_idle が共有する低レベル read。"""
    try:
        size = path.stat().st_size
        with open(path, "rb") as f:
            f.seek(max(0, size - tail_bytes))
            data = f.read()
    except OSError:
        return None
    out: list[dict] = []
    for raw in data.split(b"\n"):
        if not raw.strip():
            continue
        try:
            out.append(json.loads(raw))
        except (json.JSONDecodeError, ValueError):
            continue
    return out


def compute_busy_from_tail(path: Path, tail_bytes: int = 32768) -> bool:
    """JSONL 末尾を読んで現在の busy を算出する (= monitor 初回 / path 切替時の初期化用)。
    後ろから最初に当たった分類シグナル (= classify_jsonl_line 経由) で決める。"""
    lines = _read_tail_lines(path, tail_bytes)
    if not lines:
        return False
    for d in reversed(lines):
        kind = classify_jsonl_line(d)
        if kind == LineKind.IN_PROGRESS:
            return True
        if kind == LineKind.END or kind == LineKind.INTERRUPT:
            return False
        if kind == LineKind.START:
            return True
    return False


def busy_after_idle(path: Path, tail_bytes: int = 32768) -> bool:
    """idle watchdog 用の busy 再判定。 monitor が busy=True のまま長時間 JSONL が静かな時に呼ぶ。

    通常の tail 判定 (compute_busy_from_tail) との違いは 1 点だけ:
    **末尾の決定的 assistant 行が stop_reason を持たない** (= LineKind.OTHER で assistant)
    場合、 通常判定は「partial かも」 と見て古い行へ走査を続けるが、 idle 判定では**終端
    マーカー欠落 (= claude-code #22566) とみなして settled=False** を返す。 長時間 新規行
    ゼロなら streaming 途中ではあり得ず、 応答済みと判断できるため安全。 IN_PROGRESS
    (= `tool_use` 末尾、 長時間ツール実行中) は busy=True を維持するので、 ツール実行中に
    誤って送信ボタンへ戻すことはない。"""
    lines = _read_tail_lines(path, tail_bytes)
    if not lines:
        return False
    for d in reversed(lines):
        kind = classify_jsonl_line(d)
        if kind == LineKind.IN_PROGRESS:
            return True
        if d.get("type") == "assistant":
            # END / OTHER (= stop_reason 欠落) ともに idle 時は settled とみなす
            return False
        if kind == LineKind.INTERRUPT:
            return False
        if kind == LineKind.START:
            return True
    return False


def attach_duration_to_result(session_id: str, line: dict, events: list[dict]) -> None:
    """assistant 行で確定 stop_reason の時、 (確定行 ts - turn 開始 ts) を duration_ms として
    events 内 result に in-place で乗せる。 開始が記録されてない (= backend 再起動跨ぎ等)
    なら何もしない。"""
    if line.get("type") != "assistant":
        return
    msg = line.get("message") or {}
    stop_reason = msg.get("stop_reason")
    if not stop_reason or stop_reason == "tool_use":
        return
    start = _turn_started_at.pop(session_id, None)
    if start is None:
        return
    end = parse_jsonl_timestamp(line.get("timestamp"))
    if end is None:
        return
    duration_ms = max(0, int((end - start) * 1000))
    for ev in events:
        if ev.get("type") == "result":
            ev["duration_ms"] = duration_ms


# --- tasks 比較正規化 (= backend-F-57) ----------------------------------------
# task_reminder の snapshot を agent_status.tasks に丸ごと差し替える経路で、 旧版は
# `items != old` の dict 全 field 比較だった。 claude TUI が再掲する snapshot に余計な
# 内部 field (= timestamp / 内部メタ) が紛れたり、 順序が入れ替わったりすると、 本質的に
# 同じ task 集合でも status_event 過剰発火 → frontend 不要再描画 (= 数 ms 損失 + 体感の
# 「忙しい感」) を招いていた。 表示に効く field だけで正規化 signature を作って比較する。
_TASK_SIG_FIELDS = ("id", "subject", "description", "activeForm", "status")


def _tasks_signature(tasks: list) -> list[tuple]:
    """task list を比較用 signature (= tuple list) に正規化する。

    各 task から表示に効く field だけを抽出し、 id 昇順で sort する (= 順序揺らぎを
    吸収)。 id 無し / 型不正 entry は ("", ...) として安全に通す。 None / 空 list は
    空 list を返す。
    """
    if not tasks:
        return []
    sigs: list[tuple] = []
    for t in tasks:
        if not isinstance(t, dict):
            continue
        sigs.append(tuple(str(t.get(f) or "") for f in _TASK_SIG_FIELDS))
    sigs.sort()
    return sigs


# --- subagent 進行中の表示 (= 0-6) ---
# Task tool 実行中、 claude は各サブエージェントの transcript をメイン JSONL ではなく
# <jsonl>/<session-id>/subagents/agent-<id>.jsonl に別ファイルで書く (= v2.1.x 形式、
# メイン JSONL に sidechain 行は来ない)。 その最新ファイルの最後の tool_use 名を拾って
# 「↳ Read」 等と Task 行に inline 表示する。 並列サブエージェント時は mtime 最新の 1 つ
# だけを単一値で出す (= 割り切り、 frontend は status.subagent.last_tool を単一読み)。
_SUBAGENT_TAIL_BYTES = 65536


def scan_subagent_tail(jsonl_path: Path, since: float) -> tuple[Path, list[dict]] | None:
    """subagents/ の mtime 最新 agent-*.jsonl を末尾 1 パスで scan し、 (path, records)
    を返す pure 共通基盤 (= backend-F-18)。

    records: 末尾 _SUBAGENT_TAIL_BYTES に出てきた assistant tool_use ブロックを {name,
    id, input?} 形で時系列収集したもの (= 最後の要素が最新)。 失敗 / 候補無しは None。

    旧 latest_subagent_tool は name だけを返す薄い API で、 routes/subagents.py 側
    `_scan_agent_file` が同じ tail 読み + 行 parse を別実装で持っていた。 ここに集約
    することで subagents 側 consumer (= W1-D round 2-b 担当) も再利用できる。
    """
    subdir = jsonl_path.parent / jsonl_path.stem / "subagents"
    try:
        candidates = [
            p for p in subdir.glob("agent-*.jsonl") if p.stat().st_mtime >= since
        ]
    except OSError:
        return None
    if not candidates:
        return None
    try:
        newest = max(candidates, key=lambda p: p.stat().st_mtime)
        size = newest.stat().st_size
        with open(newest, "rb") as f:
            # 毎 tick 全読みを避け、 末尾チャンクだけ読む (= 最後の tool_use が末尾近くに居る)
            if size > _SUBAGENT_TAIL_BYTES:
                f.seek(size - _SUBAGENT_TAIL_BYTES)
                f.readline()  # seek 直後の途中行を捨てる
            data = f.read()
    except OSError:
        return None
    records: list[dict] = []
    for raw in data.decode("utf-8", errors="replace").split("\n"):
        raw = raw.strip()
        if not raw:
            continue
        try:
            obj = json.loads(raw)
        except json.JSONDecodeError:
            continue
        if obj.get("type") != "assistant":
            continue
        for block in (obj.get("message") or {}).get("content") or []:
            if isinstance(block, dict) and block.get("type") == "tool_use":
                name = block.get("name")
                if name:
                    records.append({
                        "name": name,
                        "id": block.get("id"),
                        "input": block.get("input") or {},
                    })
    return newest, records


def scan_single_agent_file(path: Path, since_offset: int = 0) -> dict:
    """1 つの agent-*.jsonl を全パスして status / last_tool を求める (= backend-F-18 export)。

    drop-in for `backend/routes/subagents.py:_scan_agent_file`: 戻り値は
    `{"lastTool": str|None, "done": bool, "lines_read": int}` で、 旧 1 関数の意味論を
    1 file scan API として export する。 since_offset は将来 incremental scan 化する
    時の差分対応のための placeholder (= 現実装は file 先頭から読む、 0 で旧挙動と互換)。

    判定規則 (= 旧 _scan_agent_file と同一):
    - last_tool: 最後に現れた tool_use の name
    - done: 最後に出た **確定 stop_reason** (= tool_use 以外) より後に tool_result が無い

    旧実装は assistant 行のたびに done を再評価 → 直後の null stop_reason 行で
    false に上書きされる罠があり、 走り終わったエージェントが running のまま固まる
    ことがあった。 1 パス回して「最後の確定 stop_reason の index」 と「最後の
    tool_result の index」 を比較する方式 (2026-06-12 修正と同型)。
    """
    last_tool: str | None = None
    last_stop_idx = -1
    last_tool_result_idx = -1
    lines_read = 0
    try:
        with path.open() as fh:
            if since_offset:
                try:
                    fh.seek(since_offset)
                except OSError:
                    # benign: optimistic seek to last-known offset; failure means we read
                    # from the start which is slower but always correct.
                    pass
            for i, raw in enumerate(fh):
                lines_read += 1
                try:
                    line = json.loads(raw)
                except json.JSONDecodeError:
                    continue
                msg = line.get("message") or {}
                content = msg.get("content")
                if isinstance(content, list):
                    for b in content:
                        if isinstance(b, dict) and b.get("type") == "tool_use":
                            name = b.get("name")
                            if name:
                                last_tool = name
                if line.get("type") == "assistant":
                    sr = msg.get("stop_reason")
                    if sr and sr != "tool_use":
                        last_stop_idx = i
                elif isinstance(content, list) and any(
                    isinstance(b, dict) and b.get("type") == "tool_result" for b in content
                ):
                    last_tool_result_idx = i
    except OSError:
        # benign: JSONL was unlinked/rotated mid-scan — defaults below (last_stop_idx=-1,
        # last_tool_result_idx=-1) yield done=False, which is the safe answer for callers.
        pass
    done = last_stop_idx >= 0 and last_stop_idx > last_tool_result_idx
    return {"lastTool": last_tool, "done": done, "lines_read": lines_read}


def latest_subagent_tool(jsonl_path: Path, since: float) -> str | None:
    """jsonl_path 対応の subagents/ で mtime 最新かつ since 以降に更新された
    agent-*.jsonl を読み、 最後の assistant tool_use 名を返す。 無ければ None。

    since で絞るのは、 同一 session の subagents/ に過去 Task の古い agent ファイルが
    残るため (= 現 Task の started_at 以降に書かれたものだけを対象にして stale 表示を
    防ぐ)。 scan は共通基盤 scan_subagent_tail に委譲 (= backend-F-18)。
    """
    result = scan_subagent_tail(jsonl_path, since)
    if result is None:
        return None
    _, records = result
    if not records:
        return None
    return records[-1].get("name")


def refresh_subagent_status(session_id: str, jsonl_path: Path) -> bool:
    """current_tool が Task の間だけ subagent.last_tool を最新化する。 変化があれば True。

    Task 非実行中に subagent が残っていれば落とす (= tool_result / Stop hook clear の保険)。
    """
    a = agent_status.get(session_id)
    if a is None:
        return False
    cur = a.get("current_tool")
    if not (cur and cur.get("name") == "Task"):
        if a.get("subagent") is not None:
            a["subagent"] = None
            return True
        return False
    name = latest_subagent_tool(jsonl_path, cur.get("started_at") or 0)
    new_val = {"last_tool": name} if name else None
    if a.get("subagent") != new_val:
        a["subagent"] = new_val
        return True
    return False


# --- hook / JSONL 共通の AskUserQuestion / Stop 即時 mutate helper -----------
# 旧設計は hooks.py が agent_status を直 mutate (= F-12 Stop で current_tool=None /
# F-69 PreToolUse で pending_question 立て) し、 JSONL tail (= mutate_agent_status) が
# 後から id 補完 / 同じ field を上書きする 2 経路並走だった。 hook が先勝ちすると
# pending_question.tool_use_id が None 固定で固まったり、 同 questions の重複到着で
# 既知 id が消える race があった (= backend-F-69)。
#
# ここに集約する `apply_pending_question` / `apply_immediate_stop` は merge ロジック
# 入りで、 hook も JSONL tail も**同じ関数**を呼ぶ。 hook 経由は「JSONL tail を待たない
# 即時起こし trigger」、 JSONL 経由は「id 補完 + 整合性確定」 の役割になる (= 同じ
# state へ向かう 2 入力が merge で収束)。 status_event.set / sessions_overview.notify
# も内部で完結し、 caller は何回呼んでも idempotent。

def apply_pending_question(
    session_id: str,
    questions: list,
    tool_use_id: str | None = None,
) -> bool:
    """AskUserQuestion の pending_question を merge ロジックで立てる (= backend-F-69)。

    merge 規則:
    - 既存 pending_question なし → 新規 (questions + tool_use_id) を set
    - 既存 questions と新着 questions が同じ → tool_use_id だけ補完
      (= hook が None で立てた後 JSONL tool_use 行で id 来る正常経路、 旧来挙動を維持)
      また hook の重複到着で既知 id を消さない (= None で上書きしない)
    - 既存 questions と新着 questions が異なる → 新規 (= 別質問に切り替わった)
    - 既存 tool_use_id != None かつ新着 tool_use_id != None かつ id 違い → 新規
      (= 連続して別質問が来た正常経路)

    変化があれば True を返す + status_event.set + sessions_overview.notify。
    questions が空なら何もせず False (= 無意味な mutate を弾く)。
    """
    if session_id not in agent_status:
        return False
    if not questions:
        return False
    a = agent_status[session_id]
    cur = a.get("pending_question")
    new: dict
    if cur is None:
        new = {"tool_use_id": tool_use_id, "questions": questions}
    else:
        cur_qs = cur.get("questions")
        cur_id = cur.get("tool_use_id")
        if cur_qs == questions:
            # 同じ質問: id だけ補完。 既知 id を None で上書きしない (= hook 重複保護)
            merged_id = cur_id if (tool_use_id is None and cur_id is not None) else (tool_use_id or cur_id)
            if merged_id == cur_id:
                return False  # 変化なし
            new = {"tool_use_id": merged_id, "questions": cur_qs}
        else:
            new = {"tool_use_id": tool_use_id, "questions": questions}
    if cur == new:
        return False
    a["pending_question"] = new
    st = stream_states.get(session_id)
    if st is not None:
        st.status_event.set()
        sessions_overview.notify()
    return True


def apply_immediate_stop(session_id: str) -> bool:
    """Stop hook 経由で turn 完了を即時反映する (= backend-F-12)。

    旧 hooks.py は agent_status を直 mutate して current_tool / subagent を落としていた。
    JSONL tail (= mutate_agent_status の stop_reason 確定経路) も同じ field を落とすので、
    本関数は「JSONL tail 到着を待たない加速」 役。 mutate 経路は session_status 1 本に
    絞り、 hook はこの関数を呼ぶだけ。

    変化があれば True を返す + status_event.set + sessions_overview.notify。
    """
    if session_id not in agent_status:
        return False
    a = agent_status[session_id]
    changed = False
    if a.get("current_tool") is not None:
        a["current_tool"] = None
        changed = True
    if a.get("subagent") is not None:
        a["subagent"] = None
        changed = True
    if changed:
        st = stream_states.get(session_id)
        if st is not None:
            st.status_event.set()
            sessions_overview.notify()
    return changed


def mutate_agent_status(session_id: str, line: dict) -> bool:
    """JSONL 1 行から agent_status を更新する。 変化があれば True を返す
    (= caller が status_event.set() するための合図)。

    PTY 経路では SDK の structured message が無いので、 JSONL の type/content から
    todos / plan_mode / current_tool / ctx_pct / model を直接拾う。
    """
    if not isinstance(line, dict) or line.get("isSidechain") or line.get("isMeta"):
        return False
    if session_id not in agent_status:
        return False
    a = agent_status[session_id]
    changed = False
    line_type = line.get("type")

    if line_type == "assistant":
        msg = line.get("message") or {}
        # TaskCreate / TaskUpdate の tool_use を見て agent_status.tasks を即時反映する。
        # task_reminder は次ターンでしか再掲されないので、 TaskCreate 直後にパネル開いても
        # 何も出ない罠を避ける (= 2026-06-12 修正)。
        content_now = msg.get("content") or []
        if isinstance(content_now, list):
            tasks_changed_local = False
            tasks = [dict(t) for t in (a.get("tasks") or [])]
            for block in content_now:
                if not isinstance(block, dict) or block.get("type") != "tool_use":
                    continue
                tname = block.get("name")
                tinput = block.get("input") or {}
                if tname == "TaskCreate":
                    subject = tinput.get("subject") or ""
                    if subject and not any(t.get("subject") == subject for t in tasks):
                        tasks.append({
                            "id": str(len(tasks) + 1),
                            "subject": subject,
                            "description": tinput.get("description") or "",
                            "activeForm": tinput.get("activeForm") or "",
                            "status": "pending",
                            "blocks": [], "blockedBy": [],
                        })
                        tasks_changed_local = True
                elif tname == "TaskUpdate":
                    tid = tinput.get("taskId")
                    if tid is None:
                        continue
                    tid = str(tid)
                    for t in tasks:
                        if str(t.get("id")) == tid:
                            for k in ("status", "subject", "description", "activeForm"):
                                v = tinput.get(k)
                                if v is not None and t.get(k) != v:
                                    t[k] = v
                                    tasks_changed_local = True
                            break
            if tasks_changed_local:
                a["tasks"] = tasks
                changed = True
        # model 表示用 (= StatusBar 5h/7d/ctx と並ぶ model 名)
        model_raw = msg.get("model")
        if model_raw:
            new_model = format_model_name(model_raw)
            if a.get("model") != new_model:
                a["model"] = new_model
                changed = True
        # usage → ctx_pct (= rate-limits.jsonl 由来とは別経路の保険)
        usage = msg.get("usage")
        if usage:
            ctx_window = a.get("ctx_window") or 1_000_000
            new_pct = compute_ctx_pct(usage, ctx_window)
            if a.get("ctx_pct") != new_pct:
                a["ctx_pct"] = new_pct
                changed = True
        # tool_use 解析: TodoWrite (進捗) / Enter|ExitPlanMode (plan_mode) / current_tool
        content = msg.get("content") or []
        if isinstance(content, list):
            for block in content:
                if not isinstance(block, dict) or block.get("type") != "tool_use":
                    continue
                name = block.get("name")
                tool_id = block.get("id")
                inp = block.get("input") or {}
                if name == "ExitPlanMode":
                    # backend-F-14: bounded set で「処理済 tool_use_id」 を覚えておき、
                    # pending_plan が clear (= ユーザ承認 / 別 plan で上書き) された後に
                    # 同 tool_id が再到着しても capture を二重起動しない。 旧版の
                    # `a["pending_plan"]["tool_use_id"] == tool_id` gate は pending_plan
                    # 生存中の SSE / monitor 二重 mutate しか弾けず、 clear 後の重複に
                    # 穴があった。
                    if not _remember_exit_plan(session_id, tool_id):
                        continue
                if name == "TodoWrite":
                    todos = inp.get("todos")
                    if todos is not None and a.get("todos") != todos:
                        a["todos"] = todos
                        changed = True
                elif name == "ExitPlanMode":
                    # plan_mode フラグは落とす (= 旧経路と同じ semantics)
                    if a.get("plan_mode"):
                        a["plan_mode"] = False
                        changed = True
                    # 承認待ち状態を立てる → frontend が PlanApprovalBubble を表示する
                    a["pending_plan"] = {
                        "tool_use_id": tool_id,
                        "plan": inp.get("plan", ""),
                        "choices": [],  # 0.5s 後に tmux capture-pane で抽出
                    }
                    changed = True
                    # 選択肢抽出は async タスクで遅延実行 (= claude TUI の prompt 描画待ち)
                    asyncio.create_task(capture_plan_choices(session_id, tool_id))
                elif name == "EnterPlanMode" and not a.get("plan_mode"):
                    a["plan_mode"] = True
                    changed = True
                elif name == "AskUserQuestion":
                    # backend-F-69: hook 側で `pending_question` を立てる仕様 (= 先勝ち
                    # で上書き) を merge ロジックに切替済。 hook と JSONL tail のどちらが
                    # 先に来ても同じ state に収束する (= 同 questions なら id 補完、
                    # 異なれば新規)。 apply_pending_question が status_event.set /
                    # sessions_overview.notify を内包するため、 ここでは戻り値だけ
                    # changed に伝播する。
                    qs_in = inp.get("questions") or []
                    if isinstance(qs_in, list) and qs_in:
                        if apply_pending_question(session_id, qs_in, tool_use_id=tool_id):
                            changed = True
                # current_tool: ActivityBar / 旧 SDK 経路と同型の「今走ってる tool」 情報
                a["current_tool"] = {
                    "name": name,
                    "id": tool_id,
                    "started_at": time.time(),
                }
                changed = True
        # stop_reason 確定 turn では current_tool を解放 (= 次 turn 開始まで空に)
        stop_reason = msg.get("stop_reason")
        if stop_reason and stop_reason != "tool_use":
            if a.get("current_tool") is not None:
                a["current_tool"] = None
                changed = True
    elif line_type == "user":
        # tool_result が来たら、 対応する current_tool が居れば解放
        msg = line.get("message") or {}
        content = msg.get("content")
        if isinstance(content, list):
            for block in content:
                if not isinstance(block, dict) or block.get("type") != "tool_result":
                    continue
                tu_id = block.get("tool_use_id")
                cur = a.get("current_tool")
                if cur and cur.get("id") == tu_id:
                    a["current_tool"] = None
                    changed = True
                # ExitPlanMode の承認 / 拒否が tool_result で返ったら pending_plan を解除
                pending = a.get("pending_plan")
                if pending and pending.get("tool_use_id") == tu_id:
                    a["pending_plan"] = None
                    changed = True
                # AskUserQuestion の回答が tool_result で返ったら pending_question を解除
                # (= ライブ overlay を消す。 以降は JSONL 由来の回答済みバブルが chat に残る)
                pq = a.get("pending_question")
                if pq and pq.get("tool_use_id") == tu_id:
                    a["pending_question"] = None
                    changed = True
    elif line_type == "mode":
        m = line.get("mode") or ""
        if m and a.get("mode") != m:
            a["mode"] = m
            changed = True
    elif line_type == "permission-mode":
        pm = line.get("permissionMode") or ""
        if pm and a.get("permission_mode") != pm:
            a["permission_mode"] = pm
            changed = True
    elif line_type == "attachment":
        att = line.get("attachment") or {}
        if att.get("type") == "budget_usd":
            for k_src, k_dst in (("used", "budget_used"), ("total", "budget_total"), ("remaining", "budget_remaining")):
                v = att.get(k_src)
                if v is not None and a.get(k_dst) != v:
                    a[k_dst] = v
                    changed = True
        elif att.get("type") == "task_reminder":
            # task_reminder の content は現在の task list 全体の snapshot (= claude TUI が
            # 毎ターン再掲)。 最新を真値として agent_status.tasks を丸ごと差し替える。
            items = att.get("content") if isinstance(att.get("content"), list) else []
            old = a.get("tasks") or []
            # backend-F-57: dict 全 field 比較 (= items != old) では task_reminder に余計な
            # field (= 順序違い / 内部メタ追加) で false positive を起こし、 status_event の
            # 過剰発火 + frontend の不要再描画を招いていた。 ID + 表示 field だけで正規化
            # 比較する。
            if _tasks_signature(items) != _tasks_signature(old):
                a["tasks"] = items
                changed = True
    elif line_type == "pr-link":
        repo = line.get("prRepository") or ""
        num = line.get("prNumber")
        url = line.get("prUrl") or ""
        if num is not None:
            pr_links = a.get("pr_links") or []
            if not any(p.get("prRepository") == repo and p.get("prNumber") == num for p in pr_links):
                a["pr_links"] = [*pr_links, {"prRepository": repo, "prNumber": num, "prUrl": url}]
                changed = True
    return changed
