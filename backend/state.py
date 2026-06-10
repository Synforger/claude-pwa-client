"""プロセス内で共有する状態 (シングルプロセス FastAPI 前提)。

`session_id` (= UI 上の 1 セッション = 1 議題) を一意キーとして、 全状態を保持する。
セッションは作成時に `agent_id` (config.json AGENTS の key) を 1 つ持ち、
それによって cwd / 通知タイトル既定値などの定義を引く。 同じ agent_id を持つ
セッションは複数同時に存在できる (= 同じ作業ディレクトリで複数議題を並行で持てる)。

- セッション定義 (`sessions_meta`): 永続化、 session_meta.json
- ストリームごとの状態 (`stream_states`)
- ステータスキャッシュ (`agent_status`, `shared_status`)

異なるモジュールから書き換えたい値は dict や dataclass にラップして
import 越しに mutate できる形にしている。
"""
import asyncio
import json
import logging
import os
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path

from config import AGENTS

logger = logging.getLogger(__name__)


def atomic_write_text(path: Path, content: str) -> None:
    """tmp ファイルに書いて os.replace で差し替える atomic write。
    書き込み途中に kill されても元ファイルは壊れない。 同一 FS 内のみ atomic。"""
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(content)
    os.replace(tmp, path)

# --- 永続化パス ---
SESSION_META_PATH = Path(__file__).parent / "session_meta.json"

# SDK が ResultMessage.model_usage で contextWindow を返してくれない / agent_status にもまだ
# 入ってない初回の fallback 値。 Sonnet / Opus の最大コンテキスト相当 (= 1M tokens)。
# usage.py からも参照されるが、 依存方向は usage → state に固定する (= state は usage を import しない)
# ことで module init 時の循環 import を回避する。
DEFAULT_CTX_WINDOW = 1_000_000


# --- セッション定義 (= UI 上の 1 タブ) ---
# セッションごとの通知モード (= ⋯ メニューで切替)。 Web Push の制約上「音のみ (バナー無し)」 は
# 作れないので 3 値: both=音+バナー / banner=消音バナー / off=このセッションは通知しない。
NOTIFY_MODES = ("both", "banner", "off")


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

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "agent_id": self.agent_id,
            "title": self.title,
            "created_at": self.created_at,
            "notify_mode": self.notify_mode,
            "parent_id": self.parent_id,
            "resume_session_id": self.resume_session_id,
        }


def _default_title(agent_id: str, index: int) -> str:
    cfg = AGENTS.get(agent_id) or {}
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
            if not sid or aid not in AGENTS:
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
            )
    else:
        # 初期化: agent ごと 1 セッションを生成する
        per_agent_idx: dict[str, int] = {}
        now = int(time.time())
        for agent_id in AGENTS:
            sid = _new_session_id()
            per_agent_idx[agent_id] = per_agent_idx.get(agent_id, 0) + 1
            sessions_meta[sid] = SessionDef(
                id=sid,
                agent_id=agent_id,
                title=_default_title(agent_id, per_agent_idx[agent_id]),
                created_at=now,
            )
        _persist_meta(sessions_meta)  # 永続化 (起動時 1 回のみ)

    return sessions_meta


def _persist_meta(meta: dict[str, SessionDef]) -> None:
    atomic_write_text(
        SESSION_META_PATH,
        json.dumps(
            [m.to_dict() for m in meta.values()],
            ensure_ascii=False,
            indent=2,
        ),
    )


def save_sessions_meta() -> None:
    _persist_meta(sessions_meta)


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


def _make_agent_status(agent_id: str) -> dict:
    cfg = AGENTS.get(agent_id) or {}
    return {
        "ctx_pct": 0,
        "ctx_window": DEFAULT_CTX_WINDOW,
        "model": cfg.get("model", ""),
        "plan_mode": False,
        "current_tool": None,
        "todos": None,
        "subagent": None,
        # ExitPlanMode の承認待ち情報。 tool_use 発火で set / tool_result で clear。
        # frontend が PlanApprovalBubble を表示するためのソース。
        # {tool_use_id: str, plan: str, choices: [{key: str, label: str}, ...]} または None
        "pending_plan": None,
        # AskUserQuestion のライブ表示用。 claude は AskUserQuestion で停止中、 会話ログ
        # (JSONL) を回答までディスクに flush しないので、 JSONL tail では質問をライブ検出
        # できない。 そこで PreToolUse hook (= 質問表示時にリアルタイム発火) で立て、
        # 回答後 flush の JSONL tool_result で clear する。 tool_use_id は hook payload に
        # 無いので None で立て、 JSONL の AskUserQuestion tool_use 行で補完する。
        # {tool_use_id: str|None, questions: [...]} または None
        "pending_question": None,
    }


stream_states: dict[str, StreamState] = {
    sid: StreamState(agent_id=meta.agent_id) for sid, meta in sessions_meta.items()
}

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
) -> SessionDef:
    """新規セッションを登録して全状態 dict を初期化する。 永続化まで行う。

    parent_id / resume_session_id はフォーク (= 会話分岐) で生まれたタブにのみ渡す
    (= 出自と、 初回 spawn で resume する claude session id)。
    """
    if agent_id not in AGENTS:
        raise ValueError(f"Unknown agent_id: {agent_id}")
    sid = _new_session_id()
    if not title:
        existing_count = sum(1 for m in sessions_meta.values() if m.agent_id == agent_id)
        title = _default_title(agent_id, existing_count + 1)
    meta = SessionDef(
        id=sid, agent_id=agent_id, title=title, created_at=int(time.time()),
        parent_id=parent_id, resume_session_id=resume_session_id,
    )
    sessions_meta[sid] = meta
    stream_states[sid] = StreamState(agent_id=agent_id)
    agent_status[sid] = _make_agent_status(agent_id)
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
    save_sessions_meta()
    return True


def rename_session(session_id: str, title: str) -> bool:
    if session_id not in sessions_meta or not title:
        return False
    sessions_meta[session_id].title = title
    save_sessions_meta()
    return True


def set_notify_mode(session_id: str, mode: str) -> bool:
    """セッションの通知モード (both / banner / off) を設定して永続化する。"""
    if session_id not in sessions_meta or mode not in NOTIFY_MODES:
        return False
    sessions_meta[session_id].notify_mode = mode
    save_sessions_meta()
    return True


# SDK レスポンス / HTTP header の解析と agent_status / shared_status の更新は
# `usage.py` に分離した (2026-05-17)。 state.py は純粋に state の定義 / lifecycle に専念。
