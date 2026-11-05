"""session CRUD + フォーク + リスタート + 削除 (= 旧 chat.py から分割、 backend-F-28 /
crosscut-F-04)。

責務:
- GET    /sessions                        : list
- POST   /sessions                        : 作成
- PATCH  /sessions/{sid}                  : title / notify_mode 変更
- POST   /sessions/{sid}/fork             : フォーク (= jsonl 鎖を新 claude_sid で書き出し)
- POST   /sessions/{sid}/restart          : claude プロセス kill + spawn (= 文脈リセット)
- POST   /sessions/{sid}/account          : 同じタブのまま口座を移して会話を続ける
- DELETE /sessions/{sid}                  : 完全削除 + フォーク産 jsonl GC

session メタ / status SSE / accounts は別 module (= overview.py / accounts.py)。
"""
from __future__ import annotations

import asyncio
import logging

from fastapi import APIRouter, Body, Depends, HTTPException

from backend._common import state
from backend._common.config import AGENTS, get_config
from backend._common.errors import raise_error
from backend._common.state import (
    SessionDef,
    register_session,
    rename_session,
    sessions_meta,
    sessions_overview,
    set_notify_mode,
    session_tmp_files,
    stream_states,
    unregister_session,
)
from backend.accounts.account_move import move_tab_account
from backend.accounts.tab_restart import reset_tab_status, stop_tab_claude
from backend.fork.lineage import write_lineage
from backend.terminal import input_ready
from backend.terminal.child_folder import clear_child_folder
from backend.terminal.runner import pty_sessions
from backend.terminal.tab_stop import stop_tab
from backend.terminal.tab_tier import tab_tier
import backend.jsonl.jsonl_watcher as jsonl_watcher

logger = logging.getLogger(__name__)

router = APIRouter()


def require_session(session_id: str) -> str:
    """path の session_id が存在しなければ 404 を投げる FastAPI 依存。 各 endpoint で
    重複していた存在チェックを 1 箇所に集約する (= Depends(require_session) で受ける)。"""
    if session_id not in sessions_meta:
        raise HTTPException(status_code=404, detail=f"Session '{session_id}' not found")
    return session_id


def session_row(meta: SessionDef) -> dict:
    """A tab as the screen lists it: the stored definition plus the tier its agent started in
    (= `null` when that is not known; never a guessed value)."""
    return {**meta.to_dict(), "tier": tab_tier(meta.id)}


# --- セッション CRUD ---
@router.get("/sessions")
def list_sessions():
    return [session_row(m) for m in sessions_meta.values()]


@router.post("/sessions")
async def create_session(payload: dict = Body(...)):
    from backend._common.config import ACCOUNTS  # noqa: PLC0415
    agent_id = payload.get("agent_id")
    title = payload.get("title")
    account_id = payload.get("account_id")
    if not agent_id or agent_id not in AGENTS:
        raise_error(400, "invalid_agent_id", "agent_id が無効です")
    if account_id is not None and account_id not in ACCOUNTS:
        raise_error(400, "invalid_account_id", "account_id が無効です")
    meta = register_session(agent_id, title, account_id=account_id)
    # 新規タブ作成時点で PTY spawn + launch_alias 投入を完了させる。 既存挙動 (=
    # /jsonl/stream/all 接続の起動 sweep) は接続時点の sessions_meta snapshot しか
    # 見ないので、 接続継続中に新 sid を追加しても ensure を踏まず、 「ターミナル
    # を表示」 を押して /ws/pty/{sid} 接続時に初めて spawn が走る = chat view 単独
    # では起動が完結しない症状の根治 (2026-06-29 確認)。 ensure 内に既存ガード
    # (= pty_sessions / has_tmux_session 早期 return) があるので二重化 safe。
    from backend.terminal.routes import ensure_pty_session_for  # noqa: PLC0415
    try:
        await ensure_pty_session_for(meta.id)
    except Exception:
        logger.exception("create_session spawn phase failed for %s", meta.id)
    return session_row(meta)


@router.patch("/sessions/{session_id}")
def patch_session(session_id: str, payload: dict = Body(...), _: str = Depends(require_session)):
    title = payload.get("title")
    notify_mode = payload.get("notify_mode")
    touched = False
    if isinstance(title, str) and title.strip():
        rename_session(session_id, title.strip())
        touched = True
    if notify_mode is not None:
        if not set_notify_mode(session_id, notify_mode):
            raise_error(400, "invalid_notify_mode", "notify_mode は both / banner / off")
        touched = True
    if not touched:
        raise_error(400, "title_or_notify_required", "title または notify_mode が必要")
    return session_row(sessions_meta[session_id])


@router.post("/sessions/{session_id}/fork")
async def fork_session(session_id: str, payload: dict = Body(...), _: str = Depends(require_session)):
    """会話を任意メッセージから分岐する (= フォーク)。

    body: {from_uuid}。 from_uuid を leaf に parentUuid 鎖を根まで遡った lineage を、 新しい
    claude session の jsonl として元と同じ project dir に書き出す。 その session を
    `claude --resume` で開く新タブ (= SessionDef、 parent_id + resume_session_id 付き) を
    登録して返す。 元タブ・元 jsonl には一切触れない。
    """
    from_uuid = payload.get("from_uuid")
    if not isinstance(from_uuid, str) or not from_uuid:
        raise_error(400, "from_uuid_required", "from_uuid が必要です")

    parent = sessions_meta[session_id]
    new_claude_id = (await asyncio.to_thread(write_lineage, session_id, from_uuid, None)).claude_id

    new_meta = register_session(
        parent.agent_id,
        title=f"{parent.title} fork",
        parent_id=session_id,
        resume_session_id=new_claude_id,
        # 親の account_id を必ず継ぐ (= 2026-07-22 fork 空タブ根治)。 lineage jsonl は
        # 親 jsonl と同じ project dir (= 親 account の CLAUDE_CONFIG_DIR 配下、 例 work =
        # ~/.claude-work/projects/...) に書かれる。 一方 spawn 時の CLAUDE_CONFIG_DIR は
        # new_meta.account_id → ACCOUNTS[...].env で決まる (= terminal/routes.py)。 ここで
        # account_id を渡さないと fork は personal (~/.claude) 扱いになり、 `claude --resume
        # <new_claude_id>` が work 配下の lineage を見つけられず rc=0 即 exit → pane は zsh
        # プロンプトに残る (= fork は fallback watchdog も無いので永久に空タブ)。
        account_id=parent.account_id,
    )
    # 新タブの monitor tail を初回 bind 扱いに固定 (= 2026-06-30 stream-from-zero)。
    # fork は backend が事前に lineage 全行を書いた新 jsonl を register してから claude
    # が `--resume <new_claude_id>` で起動し boot 行 / 新規 user/agent を追記する 2 段経路。
    # tail を初回 bind にしておかないと、 path 切替検知の旧設計 (= offset=st_size) で
    # 親 lineage 全行が skip される (= 新タブ開いても会話履歴が見えない) + claude boot
    # 後の最初の応答も st_size 採用窓で巻き添え skip される race を踏む。 reset 経由で
    # offset=0 → events.py filter で boot banner 除外 → lineage + 新規行が live で届く。
    from backend.jsonl.routes import request_sid_tail_reset  # noqa: PLC0415
    request_sid_tail_reset(new_meta.id)
    # 新タブ作成時点で PTY spawn + launch_alias 投入を完了させる (= create_session 経路と同じ
    # 横展開、 2026-06-30)。 旧実装は spawn を呼ばず、 fork 後にユーザが「ターミナル表示」 を
    # 押して /ws/pty/{new_sid} 接続するまで spawn しないので、 chat view 単独では claude が
    # 起動せず初回発話が届かない症状になっていた (= PR #29 で create/restart に入れた fix が
    # fork 経路にだけ抜けていた)。
    from backend.terminal.routes import ensure_pty_session_for  # noqa: PLC0415
    try:
        await ensure_pty_session_for(new_meta.id)
    except Exception:
        logger.exception("fork_session spawn phase failed for %s", new_meta.id)
    return session_row(new_meta)


@router.post("/sessions/{session_id}/restart")
async def restart_session(session_id: str, _: str = Depends(require_session)):
    """claude プロセスを kill + 新規 spawn する (= /clear と違ってプロセスメモリも完全解放)。
    新 claude_sid に切り替わるが SessionStart hook で bindings 更新されるので、 PWA タブは
    シームレスに続けて使える。 長期稼働で claude プロセスメモリが累積する問題への対策。"""
    await stop_tab_claude(session_id)
    # フォーク産タブを通常タブ化する (= state.demote_fork_to_normal、 backend-F-44)。
    # restart のセマンティクスは「文脈リセット + プロセスリセット」 で、 fork タブの
    # resume_session_id を残したままだと再 spawn で `claude --resume <同一 id>` が走り、
    # claude CLI が重複起動を検知して即 exit (rc=0) する = ターミナルが何も変わらず終了
    # しない (2026-06-04 確認)。 fork の親文脈引き継ぎは初回 spawn で完了した役目なので、
    # restart のタイミングで resume_session_id を落として通常タブと完全に同じ launch_alias
    # 起動経路に合流させる。 fork の記録は通常タブの記録と同じに残す。 parent_id は派生履歴として残し、
    # ドロワー上の親子インデント表示は維持する。
    state.demote_fork_to_normal(session_id)
    # monitor tail を初回 bind 扱いに戻す (= 2026-06-30 stream-from-zero、 詳細は
    # `backend/jsonl/routes.py` `_initialize_sid_tail` docstring)。 旧版は path 切替
    # 検知時に offset=st_size で「既に書かれた行を skip」 する設計で、 restart 後の
    # 新 claude が boot banner / user 初発 / tool_use/tool_result / assistant final を
    # 一気に書き終えるケースで全部巻き添え skip され「結果が来るまで何も表示されない、
    # 来た瞬間に batch 表示」 という UX 退行になっていた。 reset 後は次 monitor tick で
    # offset=0 から path 内全行を publish、 chat 非表示対象は events.py の filter で除外。
    from backend.jsonl.routes import request_sid_tail_reset  # noqa: PLC0415
    request_sid_tail_reset(session_id)
    # 新規 spawn (= 同 PWA_SID で tmux 再生成 + claude 再起動 + SessionStart hook で
    # 新 claude_sid を confirm_bind)。 ensure_pty_session_for は terminal.routes に居て
    # main.py 経由で chat router 登録より後で import される ↔ chat 早期 import の循環
    # 防止のため、 ここだけ関数内 import に残す。
    from backend.terminal.routes import ensure_pty_session_for  # noqa: PLC0415
    try:
        # restart は autoresume を skip (= prefer_fresh)。 直前 claude プロセスの
        # 完全 shutdown 前に `claude --resume <直前 sid>` が走ると重複起動検知で
        # rc=0 即 exit する race (= log 観測で spawn → 2ms exited → watchdog の
        # 2s 待ちに間に合わず、 launch_alias 投入届かない、 2026-06-29 確認)。
        # restart のセマンティクス = 文脈リセット + プロセスリセットなので、
        # 直前 sid を resume するのが意味的にも矛盾。
        await ensure_pty_session_for(session_id, prefer_fresh=True)
    except Exception:
        logger.exception("restart spawn phase failed for %s", session_id)
        return {"ok": False, "reason": "spawn_failed"}
    await reset_tab_status(session_id)
    # 全 sid SSE (/sessions/status/stream) にも変化を伝える (= per-sid と整合)
    sessions_overview.notify()
    return {"ok": True}


@router.post("/sessions/{session_id}/account")
async def move_session_account(session_id: str, payload: dict = Body(...), _: str = Depends(require_session)):
    """Move a tab to another account in place: the same tab, with the same name, continues its conversation under
    `account_id`. The conversation up to its latest clean point is written into that account's projects folder,
    the tab's claude is stopped, and the tab starts again resuming it there."""
    account_id = payload.get("account_id")
    if not isinstance(account_id, str) or account_id not in (get_config().get("accounts") or {}):
        raise_error(400, "unknown_account", "そのアカウントは設定にありません")
    return session_row(await move_tab_account(session_id, account_id))


@router.delete("/sessions/{session_id}")
async def delete_session(session_id: str, _: str = Depends(require_session)):
    # PTY + tmux + JSONL binding を一括 cleanup
    input_ready.forget(session_id)
    try:
        await stop_tab(session_id)
        pty_sessions.pop(session_id, None)
        jsonl_watcher.unregister(session_id)
    except Exception:
        # delete 経路の kill 失敗 = backend に session が残るゴースト化の原因。 warning で
        # 残す (= 2026-06-22)。
        logger.warning("session cleanup failed for %s", session_id, exc_info=True)
    # A tab's memo stays: it lives in the agent's own folder, beside the tab's other pages. A child's goes with it,
    # since closing a child ends the work it was opened for.
    clear_child_folder(session_id)
    # 一時ファイルをクリーンアップ
    for p in session_tmp_files.pop(session_id, []):
        try:
            p.unlink(missing_ok=True)
        except Exception:
            logger.debug("tmp file unlink failed: %s", p, exc_info=True)
    unregister_session(session_id)
    return {"status": "ok", "session_id": session_id}


# 旧: session 別 model / effort / fast 切替 endpoint (= ⋯ メニューの ModelEffortPicker
# 用)。 2026-05-31 撤去。 設計方針「制御はターミナル」 に揃え、 切替はターミナルから
# `/model <name>` `/effort <level>` `/fast` を直打ちする (= picker で切替えても結局
# 切替確認プロンプトが出てターミナル操作が要る、 多くの場合 default 固定で十分)。
