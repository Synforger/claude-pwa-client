"""プロセス内で共有する状態 (シングルプロセス FastAPI 前提)。

`session_id` (= UI 上の 1 セッション = 1 議題) を一意キーとして、 全状態を保持する。
セッションは作成時に `agent_id` (config.json AGENTS の key) を 1 つ持ち、
それによって cwd / 通知タイトル既定値などの定義を引く。 同じ agent_id を持つ
セッションは複数同時に存在できる (= 同じ作業ディレクトリで複数議題を並行で持てる)。

- セッション定義 (`sessions_meta`): 永続化、 session_meta.json
- ストリームごとの状態 (`stream_states`)
- ステータスキャッシュ (`agent_status`, `shared_status`)
- セッション単位の `SessionState` (= 2026-06-21、 backend-F-07): 上の dict 群
  を 1 sid あたり 1 instance に束ねた view。 `asyncio.Lock` も SessionState
  内に持つので、 副 path から `async with state.get_session(sid).lock:` で
  read-modify-write を atomic 化できる。 既存の module-level dict 群は
  破壊互換のためそのまま残してあり (= 副 path consumer 移行は別 round 担当)、
  両 view が**同一 object を参照**するよう register / unregister で同期する。

異なるモジュールから書き換えたい値は dict や dataclass にラップして
import 越しに mutate できる形にしている。
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any

import backend.config as _config


def _agents() -> dict:
    """`backend.config.AGENTS` を都度 lookup (= config.py の遅延化 PEP 562
    `__getattr__` 経由)。 module 上端で bind すると test 中の `monkeypatch` で
    config を切り替えても古い dict を見続けてしまうため、 呼び出しごとに引く。
    test 側は `monkeypatch.setattr(backend.state, "_agents", lambda: {...})`
    で挙動を差し替えられる。"""
    return _config.AGENTS

logger = logging.getLogger(__name__)


def atomic_write_text(path: Path, content: str) -> None:
    """tmp ファイルに書いて os.replace で差し替える atomic write。
    書き込み途中に kill されても元ファイルは壊れない。 同一 FS 内のみ atomic。"""
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(content)
    os.replace(tmp, path)

# --- 永続化パス ---
from backend.paths import SESSION_META_PATH  # noqa: E402, F401

# SDK が ResultMessage.model_usage で contextWindow を返してくれない / agent_status にもまだ
# 入ってない初回の fallback 値。 Sonnet / Opus の最大コンテキスト相当 (= 1M tokens)。
# usage.py からも参照されるが、 依存方向は usage → state に固定する (= state は usage を import しない)
# ことで module init 時の循環 import を回避する。
DEFAULT_CTX_WINDOW = 1_000_000


# --- セッション定義 (= UI 上の 1 タブ) ---
# セッションごとの通知モード (= ⋯ メニューで切替)。 Web Push の制約上「音のみ (バナー無し)」 は
# 作れないので 3 値: both=音+バナー / banner=消音バナー / off=このセッションは通知しない。
#
# 2026-06-21 (crosscut-F-20): str ベースの Enum に昇格して typo を弾く。 旧来の
# `NOTIFY_MODES` tuple API は値 (= "both"/"banner"/"off") を返したまま温存し、
# 永続化形式 (= session_meta.json) も string の "both" / "banner" / "off" のまま
# (= frontend / sw.js consumer 修正は別 wave 担当のため、 wire format 不変)。
class NotifyMode(str, Enum):
    BOTH = "both"
    BANNER = "banner"
    OFF = "off"


NOTIFY_MODES: tuple[str, ...] = tuple(m.value for m in NotifyMode)


@dataclass
class SessionDef:
    id: str
    agent_id: str
    title: str
    created_at: int
    notify_mode: str = "both"
    # フォーク (= 会話分岐) で生まれたタブの出自。 分岐元の PWA session id を持つ。
    # ドロワで親の下にインデント表示するのに使う。 通常の新規タブは None。
    parent_id: str | None = None
    # フォークタブが初回 spawn 時に `claude --resume <id>` で開く claude session id。
    # build_forked_lineage で書き出した新 jsonl のファイル名 (= 新 claude session uuid)。
    # 通常タブ (= alias 起動) は None。
    resume_session_id: str | None = None
    # どの Claude OAuth プロファイルでこのタブを起動するか (= config.json accounts の key)。
    # spawn 時に accounts[account_id].env を CLAUDE_CONFIG_DIR 含む tmux env として注入する。
    # 既存タブとの互換性のため None = personal 相当 (= 通常 ~/.claude/) として扱う。
    account_id: str | None = None

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "agent_id": self.agent_id,
            "title": self.title,
            "created_at": self.created_at,
            "notify_mode": self.notify_mode,
            "parent_id": self.parent_id,
            "resume_session_id": self.resume_session_id,
            "account_id": self.account_id,
        }


def _default_title(agent_id: str, index: int) -> str:
    cfg = _agents().get(agent_id) or {}
    base = cfg.get("display_name") or agent_id.upper()
    return f"{base}-{index}"


def _new_session_id() -> str:
    return f"ses_{uuid.uuid4().hex[:12]}"


def _load_sessions_meta() -> dict[str, SessionDef]:
    """session_meta.json をロード。 ファイルが無い (= 初回起動) 場合は agent ごとに
    1 セッションを生成して永続化する。
    """
    meta_raw: list[dict] | None = None
    if SESSION_META_PATH.exists():
        try:
            meta_raw = json.loads(SESSION_META_PATH.read_text())
        except Exception:
            meta_raw = None

    sessions_meta: dict[str, SessionDef] = {}

    if isinstance(meta_raw, list):
        # 通常パス: session_meta.json に従う (空配列でもこちらに通す = 0 セッション起動 OK)
        for entry in meta_raw:
            if not isinstance(entry, dict):
                continue
            sid = entry.get("id")
            aid = entry.get("agent_id")
            title = entry.get("title") or aid or "session"
            created = entry.get("created_at") or int(time.time())
            if not sid or aid not in _agents():
                # agent_id が config から消えてる (= 過去 session のまま config 更新で消失)、
                # その session は UI に出せないので skip。 観測のため warn を残す。
                if sid:
                    logger.warning("session %s skipped: agent_id %r not in AGENTS", sid, aid)
                continue
            mode = entry.get("notify_mode")
            sessions_meta[sid] = SessionDef(
                id=sid, agent_id=aid, title=title, created_at=int(created),
                notify_mode=mode if mode in NOTIFY_MODES else "both",
                parent_id=entry.get("parent_id"),
                resume_session_id=entry.get("resume_session_id"),
                account_id=entry.get("account_id"),
            )
    else:
        # 初期化: agent ごと 1 セッションを生成する
        per_agent_idx: dict[str, int] = {}
        now = int(time.time())
        for agent_id in _agents():
            sid = _new_session_id()
            per_agent_idx[agent_id] = per_agent_idx.get(agent_id, 0) + 1
            sessions_meta[sid] = SessionDef(
                id=sid,
                agent_id=agent_id,
                title=_default_title(agent_id, per_agent_idx[agent_id]),
                created_at=now,
            )
        # 永続化 (起動時 1 回のみ) — module 変数 sessions_meta はまだ未定義なので
        # 同じ payload を inline で書く (= save_sessions_meta() は module 変数 bind 後にのみ呼べる)
        atomic_write_text(
            SESSION_META_PATH,
            json.dumps(
                [m.to_dict() for m in sessions_meta.values()],
                ensure_ascii=False,
                indent=2,
            ),
        )

    return sessions_meta


def save_sessions_meta() -> None:
    """sessions_meta を session_meta.json に永続化する (= 唯一の write 経路)。

    旧版は `_persist_meta(meta)` と `save_sessions_meta()` の 2 関数が並走して
    実質同じ処理を 2 行で書き分けていた (= backend-F-39)。 引数違いで分けるほど
    の差は無く、 _persist_meta は _load_sessions_meta 内の初期化 1 回でしか
    呼ばれないので、 統合して 1 関数にした。
    """
    atomic_write_text(
        SESSION_META_PATH,
        json.dumps(
            [m.to_dict() for m in sessions_meta.values()],
            ensure_ascii=False,
            indent=2,
        ),
    )


sessions_meta = _load_sessions_meta()


# --- ストリーム状態 ---
@dataclass
class StreamState:
    agent_id: str = ""  # どの AGENTS 設定 (cwd / notification_title) を参照するか
    # 状態変化シグナル (= /status/{sid}/stream SSE が wait する event)。
    # current_tool 変化 / todos 更新等 (= hooks / jsonl 経路) で set、 SSE 受信側は
    # 現状 status JSON を yield して event.clear() する。 backend→frontend を即時 push。
    status_event: asyncio.Event = field(default_factory=asyncio.Event)
    # turn 進行中か (= 推論中なら True / 完了なら False)。 全 session の JSONL を tail する
    # monitor_all_sessions_loop が assistant の stop_reason / 素ユーザ発話から算出して更新する。
    # frontend の青丸 (処理中) / 赤丸 (完了未読) / 停止ボタンの **backend 権威ソース**。
    # JSONL を直接読むので、 chat SSE の result イベント取りこぼしに依存しない (= 非アクティブ
    # タブでも追従でき、 active タブの取りこぼしも backend が拾い直せる)。
    busy: bool = False
    # ユーザが Stop ボタンを押した「意思」 を sticky で持つ。 True の間は busy 計算結果が
    # 何であれ busy=False を強制する (= 停止押した後の JSONL 末尾 (tool_use 等) で busy=True
    # に戻ったり、 別 session の overview SSE 発火で停止 session が再評価されたりしても
    # 停止ボタンが復活しない)。 次の素ユーザ発話で False にリセット。
    user_stopped: bool = False


@dataclass
class AgentStatus:
    """セッションごとの「ステータスキャッシュ」 を 1 instance に集約した dataclass
    (= 2026-06-21、 backend-F-16 / F-37 / F-38)。

    旧来の `_make_agent_status` は素 dict factory で、 field 名 typo / 不揃いの
    default が広い consumer (= routes / jsonl / hooks) に潜む構造だった。 dataclass
    化で **factory 1 箇所 / field 名 静的検査 / default 一元** を担保しつつ、
    既存の `agent_status[sid][key]` 経由 read/write 互換のために `to_dict()` で
    plain dict を吐き、 module-level `agent_status` には dict の方を入れる。
    副 path consumer (= routes/* / jsonl/*) の dataclass 直接化は round 2 担当。
    """
    ctx_pct: int = 0
    ctx_window: int = DEFAULT_CTX_WINDOW
    model: str = ""
    plan_mode: bool = False
    current_tool: dict | None = None
    todos: list | None = None
    subagent: dict | None = None
    # ExitPlanMode の承認待ち情報。 tool_use 発火で set / tool_result で clear。
    # frontend が PlanApprovalBubble を表示するためのソース。
    # {tool_use_id: str, plan: str, choices: [{key: str, label: str}, ...]} または None
    pending_plan: dict | None = None
    # AskUserQuestion のライブ表示用。 claude は AskUserQuestion で停止中、 会話ログ
    # (JSONL) を回答までディスクに flush しないので、 JSONL tail では質問をライブ検出
    # できない。 そこで PreToolUse hook (= 質問表示時にリアルタイム発火) で立て、
    # 回答後 flush の JSONL tool_result で clear する。 tool_use_id は hook payload に
    # 無いので None で立て、 JSONL の AskUserQuestion tool_use 行で補完する。
    # {tool_use_id: str|None, questions: [...]} または None
    pending_question: dict | None = None
    # Fable 5 系の jsonl が出す session-level メタ。 Opus 系 jsonl では出ないので
    # 空のまま (= 既存挙動と互換)。
    # mode: normal / plan 等
    # permission_mode: default / bypassPermissions / acceptEdits 等
    mode: str = ""
    permission_mode: str = ""
    # USD ベースの予算 (= /budget や課金ステータスで claude が記録)。 attachment
    # budget_usd 行で更新する。 None なら未記録。
    budget_used: float | None = None
    budget_total: float | None = None
    budget_remaining: float | None = None
    # このセッションで言及された PR の一覧 (= jsonl の pr-link 行から重複排除して
    # 集める)。 (prRepository, prNumber) で dedup、 古い順。 StatusBar の 🔗 chip
    # で表示する。
    pr_links: list = field(default_factory=list)
    # このセッションの task list (= attachment task_reminder の content スナップショット)。
    # claude TUI が毎ターン現状を再掲してくるので、 最新値で上書きする運用。
    # 各 entry: { id, subject, description, activeForm, status, blocks, blockedBy }。
    # 📋 専用パネルで表示する。
    tasks: list = field(default_factory=list)

    @classmethod
    def for_agent(cls, agent_id: str) -> "AgentStatus":
        """AGENTS[agent_id].model を初期 model にして factory する。"""
        cfg = _agents().get(agent_id) or {}
        return cls(model=cfg.get("model", ""))

    def to_dict(self) -> dict[str, Any]:
        """`agent_status` dict store に格納する plain dict。 dict / list は
        参照を共有して欲しいので shallow copy せず元の field をそのまま渡す
        (= 旧来挙動と同じ。 mutate された list/dict は dataclass 経由でも見える)。"""
        return {
            "ctx_pct": self.ctx_pct,
            "ctx_window": self.ctx_window,
            "model": self.model,
            "plan_mode": self.plan_mode,
            "current_tool": self.current_tool,
            "todos": self.todos,
            "subagent": self.subagent,
            "pending_plan": self.pending_plan,
            "pending_question": self.pending_question,
            "mode": self.mode,
            "permission_mode": self.permission_mode,
            "budget_used": self.budget_used,
            "budget_total": self.budget_total,
            "budget_remaining": self.budget_remaining,
            "pr_links": self.pr_links,
            "tasks": self.tasks,
        }


def _make_agent_status(agent_id: str) -> dict:
    """旧 factory 互換 wrapper。 内部は AgentStatus dataclass を経由するので
    field の追加 / default 変更は dataclass 1 箇所で済む。"""
    return AgentStatus.for_agent(agent_id).to_dict()


stream_states: dict[str, StreamState] = {
    sid: StreamState(agent_id=meta.agent_id) for sid, meta in sessions_meta.items()
}


# --- SessionState (= 1 sid を束ねた集約 view、 backend-F-07) ---
@dataclass
class SessionState:
    """1 sid 分の state を束ねる集約 dataclass。

    旧設計は `sessions_meta` / `stream_states` / `agent_status` /
    `session_tmp_files` / `session_last_seen_at` の 5 dict を sid で並走させ
    `asyncio.Lock` も無く、 read-modify-write race (= tasks 配列の lost update /
    pr_links の重複等) が GIL 任せだった。 ここでは 1 sid あたり 1 SessionState
    を作って lock を所有させる。 既存 dict 群は同じ field object を共有する
    parallel view (= 副 path consumer 移行は別 round で扱う互換のため温存)。

    使い方 (round 2 で副 path 移行後の想定):
        async with state.get_session(sid).lock:
            status = state.get_session(sid).status  # dict 参照
            status["pr_links"].append(...)

    今 wave 時点の利用者: round 2 sub-agent (= W1-A / W1-C / W1-D) が wrap する
    consumer。 backend 中央は本 round で wiring (= register/unregister 同期 +
    helper) だけを揃える。
    """
    meta: SessionDef
    stream: StreamState
    # `agent_status` dict と参照を共有する。 dataclass 化済の AgentStatus
    # field 名で field 名整合を担保したいが、 副 path consumer 互換のため
    # store は plain dict (= AgentStatus.to_dict()) のまま残す。
    status: dict[str, Any]
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    tmp_files: list[Path] = field(default_factory=list)
    # 最後にこの sid を「見た」 時刻 (= /views POST から更新)。 None は未閲覧。
    last_seen_at: float | None = None


# 実体は file 下部 (`_init_session_states` 呼び出し) で agent_status / sessions_meta /
# stream_states が出揃った後に埋める (= 評価順依存を回避)。
session_states: dict[str, SessionState] = {}


def get_session(session_id: str) -> SessionState | None:
    """SessionState を引く。 round 2 で副 path から
    `async with state.get_session(sid).lock:` する際の入口。"""
    return session_states.get(session_id)


def get_or_create_lock(session_id: str) -> asyncio.Lock:
    """既存 session の Lock を返す。 session_id が未登録なら ad-hoc Lock を作る
    (= test の monkeypatch ベース consumer がカウンタ操作で先走るケース保護)。"""
    s = session_states.get(session_id)
    return s.lock if s is not None else asyncio.Lock()

# /views/ws 接続ごとに「今その client が見ている session_id」 を保持。 接続切断 (TCP FIN /
# iOS が PWA bg 化時に socket を切る) で自動削除されるので stale 概念が発生しない。
# broadcast_push は session_id がこの set に含まれていれば送信スキップ (= ユーザが画面で
# 見ている session への通知を抑止)。 接続を connection id (= id(websocket)) で索引する。
views_by_conn: dict[str, str] = {}


def is_session_viewed(session_id: str) -> bool:
    """session_id を見ている WebSocket 接続が 1 つでもあるか。"""
    if not session_id:
        return False
    for v in views_by_conn.values():
        if v == session_id:
            return True
    return False


class OverviewBroadcaster:
    """全 session の busy / pending_question 変化を /sessions/overview/stream に push する
    fan-out。 複数接続 (= 複数デバイス / 複数タブ) が購読しても取りこぼさないよう、 1 個の
    共有 Event でなく**接続ごとの Event** を broadcaster が一括 notify する。

    旧実装は単一 asyncio.Event を全接続で共有しており、 1 接続の generator が clear() した
    瞬間に他接続の wait が起きそこねて push を落とす競合があった (= iPhone 2 台同時運用で
    「片方だけ停止ボタンが stuck」 の一因)。 接続ごとに Event を分けることで各接続が独立に
    確実に起こされる。"""

    def __init__(self) -> None:
        self._waiters: set[asyncio.Event] = set()

    def subscribe(self) -> asyncio.Event:
        ev = asyncio.Event()
        self._waiters.add(ev)
        return ev

    def unsubscribe(self, ev: asyncio.Event) -> None:
        self._waiters.discard(ev)

    def notify(self) -> None:
        """全購読接続を起こす。 同一イベントループ内からのみ呼ぶ (= asyncio.Event.set)。"""
        for ev in list(self._waiters):
            ev.set()


# 全 session の busy / pending_question 変化を全接続へ fan-out する broadcaster。
# 個別 session の status_event とは別に、 全 session 横断の 1 接続 push を担う (= 非アクティブ
# タブの青丸/赤丸 + 停止ボタンを live 追従させる経路。 タブごとに SSE を張らずに済む)。
sessions_overview = OverviewBroadcaster()


# --- JSONL event broadcaster (= F-02 / F-06) ---------------------------------
# JSONL 1 行から jsonl_line_to_events で生成した event を全 SSE 接続へ fan-out する
# pub/sub。 monitor_all_sessions_loop が**単一経路で**event 生成 + mutator 適用 +
# publish を担う。 SSE consumer (= /jsonl/stream/{sid} / /jsonl/stream/all) は
# broadcaster の Queue を listen するだけで、 自前で mutator を呼ばない (= F-06 で
# dual-driver mutate を解消)。
#
# subscriber key:
#   - sid string  : その sid だけの event を受ける (= 旧 per-sid SSE 互換)
#   - "all"       : 全 sid の event を受ける (= F-15 一括接続)
#
# Queue は asyncio.Queue で容量無制限 (= 通常 burst で数十 event、 backend 内 producer
# のみ)。 切断時は SSE generator 側で unsubscribe する。
ALL_SUBSCRIBER_KEY = "all"


class JsonlEventBroadcaster:
    """JSONL event を sid / "all" subscriber に fan-out する pub/sub。

    publish(sid, event) で 1 event を流すと:
      - subscribers[sid] の全 Queue に event を put
      - subscribers["all"] の全 Queue にも (event + sid 同梱) を put

    publish 側で sid を event payload に重ねる責務は持たない (caller が event に
    sid を埋めるか、 "all" subscriber 側で sid を見たいなら別途 wrap が必要)。
    実装の単純さのため、 "all" 経路用に publish は sid を 2nd 引数として put する
    形 (= 内部 tuple) ではなく、 caller が event dict に "sid" field を埋めてから
    publish する規約とする。 caller (= monitor 経路) は jsonl_routes._process_new_lines
    が event dict に sid を埋めた上で publish する。
    """

    def __init__(self) -> None:
        self._subs: dict[str, set[asyncio.Queue]] = {}

    def subscribe(self, key: str) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue()
        self._subs.setdefault(key, set()).add(q)
        return q

    def unsubscribe(self, key: str, q: asyncio.Queue) -> None:
        s = self._subs.get(key)
        if s is None:
            return
        s.discard(q)
        if not s:
            self._subs.pop(key, None)

    def publish(self, sid: str, event: dict) -> None:
        """1 event を sid + "all" subscriber へ fan-out。 同一 event 参照を全 Queue に
        put するので、 consumer は event を mutate しないこと (= read-only 扱い)。"""
        for q in list(self._subs.get(sid, ())):
            try:
                q.put_nowait(event)
            except asyncio.QueueFull:
                # benign: subscriber is too slow; dropping events for that one consumer is
                # intentional (= broadcaster is fan-out best-effort, fast subscribers must
                # not be penalized). The consumer eventually reconnects + replays via file.
                pass
        for q in list(self._subs.get(ALL_SUBSCRIBER_KEY, ())):
            try:
                q.put_nowait(event)
            except asyncio.QueueFull:
                # benign: same as the per-sid branch above — drop for the slow consumer
                # only, let the rest receive the event.
                pass

    def subscriber_count(self, key: str) -> int:
        """test / debug 用 (= active subscriber 数)。"""
        return len(self._subs.get(key, ()))


jsonl_event_broadcaster = JsonlEventBroadcaster()

# 各 session を「最後に確認した時刻」 を全 client 共有で持つ。 ある端末でタブを開いた
# (= activeSid 化) 時に backend に POST → ここを更新 → sessions_overview.notify() で
# 全 client に broadcast → 他端末は自分の unreadDone を比較してマーク前の last_seen より
# 古い event なら赤丸を消す。 これで iPhone と Mac の未読同期が成立する。
session_last_seen_at: dict[str, float] = {}

# --- セッションごとの一時ファイル ---
session_tmp_files: dict[str, list[Path]] = {}

# --- ステータスキャッシュ ---
shared_status: dict = {
    "five_hour_pct": 0,
    "seven_day_pct": 0,
    "five_hour_resets_at": 0,
    "seven_day_resets_at": 0,
}

agent_status: dict[str, dict] = {
    sid: _make_agent_status(meta.agent_id) for sid, meta in sessions_meta.items()
}


def _build_session_state(sid: str) -> SessionState:
    """既存 dict 群 (= sessions_meta / stream_states / agent_status / session_tmp_files /
    session_last_seen_at) と field 参照を**共有**する SessionState を生成。
    SessionState 側で list/dict を mutate しても旧 dict 経由でも見え、 逆も成立する。"""
    tmp = session_tmp_files.setdefault(sid, [])
    return SessionState(
        meta=sessions_meta[sid],
        stream=stream_states[sid],
        status=agent_status[sid],
        tmp_files=tmp,
        last_seen_at=session_last_seen_at.get(sid),
    )


def _init_session_states() -> None:
    session_states.clear()
    for sid in sessions_meta:
        session_states[sid] = _build_session_state(sid)


_init_session_states()


# backend プロセスの起動時刻 (= /status payload に含めて frontend が再起動を検知)。
# LaunchAgent KeepAlive で自動再起動した場合に、 frontend 側で stale な streaming bubble を
# 停止扱いに固定するためのシグナル。
backend_start_time: float = time.time()


# --- セッション操作ヘルパ ---
def register_session(
    agent_id: str,
    title: str | None = None,
    parent_id: str | None = None,
    resume_session_id: str | None = None,
    account_id: str | None = None,
    sid: str | None = None,
) -> SessionDef:
    """新規セッションを登録して全状態 dict を初期化する。 永続化まで行う。

    parent_id / resume_session_id はフォーク (= 会話分岐) で生まれたタブにのみ渡す
    (= 出自と、 初回 spawn で resume する claude session id)。
    account_id は config.json accounts の key (= 個人 / 会社 OAuth の選択)。 None は
    personal 相当 (= 通常 ~/.claude/) として扱う。
    sid が指定された場合は新規生成せずその値で登録する (= ADR-020 e2e seed が
    fixture 固定 sid を要求するため、 デフォルトは従来通り _new_session_id())。
    """
    if agent_id not in _agents():
        raise ValueError(f"Unknown agent_id: {agent_id}")
    if sid is None:
        sid = _new_session_id()
    if not title:
        existing_count = sum(1 for m in sessions_meta.values() if m.agent_id == agent_id)
        title = _default_title(agent_id, existing_count + 1)
    meta = SessionDef(
        id=sid, agent_id=agent_id, title=title, created_at=int(time.time()),
        parent_id=parent_id, resume_session_id=resume_session_id,
        account_id=account_id,
    )
    sessions_meta[sid] = meta
    stream_states[sid] = StreamState(agent_id=agent_id)
    agent_status[sid] = _make_agent_status(agent_id)
    session_states[sid] = _build_session_state(sid)
    save_sessions_meta()
    return meta


def unregister_session(session_id: str) -> bool:
    """セッションを完全削除。 PTY / tmux の停止は呼び出し側責任。"""
    if session_id not in sessions_meta:
        return False
    sessions_meta.pop(session_id, None)
    stream_states.pop(session_id, None)
    agent_status.pop(session_id, None)
    session_tmp_files.pop(session_id, None)
    session_last_seen_at.pop(session_id, None)
    session_states.pop(session_id, None)
    save_sessions_meta()
    return True


def rename_session(session_id: str, title: str) -> bool:
    if session_id not in sessions_meta or not title:
        return False
    sessions_meta[session_id].title = title
    save_sessions_meta()
    return True


def set_notify_mode(session_id: str, mode: str | NotifyMode) -> bool:
    """セッションの通知モード (both / banner / off) を設定して永続化する。
    NotifyMode Enum も string も受ける (= crosscut-F-20 で Enum 化、 wire 形式は string)。
    """
    if session_id not in sessions_meta:
        return False
    value = mode.value if isinstance(mode, NotifyMode) else mode
    if value not in NOTIFY_MODES:
        return False
    sessions_meta[session_id].notify_mode = value
    save_sessions_meta()
    return True


def demote_fork_to_normal(session_id: str) -> str | None:
    """フォーク産タブを通常タブに降格させる (= backend-F-44)。

    restart_session で fork タブを再 spawn する際、 `resume_session_id` が残ったままだと
    `claude --resume <同一 id>` が走り、 claude CLI が重複起動を検知して即 exit する
    (= 2026-06-04 観測、 詳細経緯は routes/sessions.py restart_session のコメント参照)。
    fork の親文脈引き継ぎは初回 spawn で完了した役目なので、 restart のタイミングで
    通常タブ化し、 役目を終えた fork jsonl も同期 GC する。

    SessionDef.resume_session_id を None に書き戻し、 永続化、 fork jsonl を unlink。
    呼び出し元 (= restart_session) は kill / spawn の流れの中でこれを 1 行呼ぶだけ。
    戻り値 = 掃除した fork resume id (= 通知 / log 用)、 元々通常タブなら None。
    """
    meta = sessions_meta.get(session_id)
    if meta is None:
        return None
    fork_resume_id = getattr(meta, "resume_session_id", None)
    if not fork_resume_id:
        return None
    meta.resume_session_id = None
    save_sessions_meta()
    # fork jsonl GC (= delete_session の GC と同型、 蓄積させない)。
    # 失敗しても restart 本体は続行 (= unlink は best-effort)。
    try:
        from backend.jsonl.watcher import _cwd_to_project_dir  # noqa: PLC0415
        cwd = (_agents().get(meta.agent_id) or {}).get("cwd")
        project_dir = _cwd_to_project_dir(cwd) if cwd else None
        if project_dir is not None:
            fork_jsonl = project_dir / f"{fork_resume_id}.jsonl"
            if fork_jsonl.exists():
                fork_jsonl.unlink(missing_ok=True)
                logger.info(
                    "fork: gc jsonl on demote session=%s file=%s",
                    session_id, fork_jsonl.name,
                )
    except Exception:
        logger.debug("fork jsonl gc on demote failed for %s", session_id, exc_info=True)
    return fork_resume_id


# SDK レスポンス / HTTP header の解析と agent_status / shared_status の更新は
# `usage.py` に分離した (2026-05-17)。 state.py は純粋に state の定義 / lifecycle に専念。
