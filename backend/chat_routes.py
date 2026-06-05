"""チャット送受信・状態問い合わせ系のエンドポイント群。

セッション (UI 上の 1 タブ = 1 議題) を一意キー session_id で扱う。

含まれるルート:
- GET  /status/{session_id}           ステータス取得 (+ /stream で SSE push)
- GET  /sessions                      セッション一覧
- POST /sessions                      新規セッション作成 (body: {agent_id, title?})
- PATCH /sessions/{session_id}        title 変更 (body: {title})
- DELETE /sessions/{session_id}       セッション削除
- GET  /agents                        agent 種別一覧 (作成時の選択肢)
- GET/PATCH /sessions/{session_id}/config  model / effort 上書き

チャット送受信そのものは PTY 経路 (pty_routes /pty/{sid}/send) + JSONL SSE
(jsonl_routes /jsonl/stream/{sid}) が担う。 ここは session メタ / status / config 専任。
"""
import asyncio
import json
import logging
import uuid

from fastapi import APIRouter, Body, Depends, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import StreamingResponse

from config import AGENTS
from usage import read_latest_rate_limits
from state import (
    agent_status,
    atomic_write_text,
    backend_start_time,
    register_session,
    rename_session,
    save_sessions_meta,
    set_notify_mode,
    session_tmp_files,
    sessions_meta,
    sessions_overview,
    shared_status,
    stream_states,
    unregister_session,
    views_by_conn,
)

logger = logging.getLogger(__name__)

router = APIRouter()


def require_session(session_id: str) -> str:
    """path の session_id が存在しなければ 404 を投げる FastAPI 依存。 各 endpoint で
    重複していた存在チェックを 1 箇所に集約する (= Depends(require_session) で受ける)。"""
    if session_id not in sessions_meta:
        raise HTTPException(status_code=404, detail=f"Session '{session_id}' not found")
    return session_id


# --- セッション CRUD ---
@router.get("/sessions")
def list_sessions():
    return [m.to_dict() for m in sessions_meta.values()]


@router.post("/sessions")
def create_session(payload: dict = Body(...)):
    agent_id = payload.get("agent_id")
    title = payload.get("title")
    if not agent_id or agent_id not in AGENTS:
        raise HTTPException(status_code=400, detail="agent_id が無効です")
    meta = register_session(agent_id, title)
    return meta.to_dict()


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
            raise HTTPException(status_code=400, detail="notify_mode は both / banner / off")
        touched = True
    if not touched:
        raise HTTPException(status_code=400, detail="title または notify_mode が必要")
    return sessions_meta[session_id].to_dict()


@router.post("/sessions/{session_id}/fork")
def fork_session(session_id: str, payload: dict = Body(...), _: str = Depends(require_session)):
    """会話を任意メッセージから分岐する (= フォーク)。

    body: {from_uuid}。 from_uuid を leaf に parentUuid 鎖を根まで遡った lineage を、 新しい
    claude session の jsonl として元と同じ project dir に書き出す。 その session を
    `claude --resume` で開く新タブ (= SessionDef、 parent_id + resume_session_id 付き) を
    登録して返す。 元タブ・元 jsonl には一切触れない。
    """
    from pty_runner import jsonl_path_for_session  # noqa: PLC0415
    from fork import build_forked_lineage, fork_point_status, lineage_root_resolved  # noqa: PLC0415
    from jsonl_watcher import _cwd_to_project_dir  # noqa: PLC0415

    from_uuid = payload.get("from_uuid")
    if not from_uuid or not isinstance(from_uuid, str):
        raise HTTPException(status_code=400, detail="from_uuid が必要です")

    parent = sessions_meta[session_id]

    # from_uuid を含む jsonl を探す。 claude は途中で session id をロール (= compact / 継続)
    # することがあり、 画面に残る古いメッセージは前のファイルに居る一方、 jsonl_path_for_session
    # は今 open 中の新ファイルを返す。 そのため「今のファイルだけ」 でなく同じ cwd の project dir
    # 内の全 jsonl を新しい順に走査して、 uuid を実際に含むファイルを source にする (= uuid は
    # 一意なので確実に当たる)。
    live = jsonl_path_for_session(session_id)
    cwd = (AGENTS.get(parent.agent_id) or {}).get("cwd")
    project_dir = _cwd_to_project_dir(cwd) if cwd else (live.parent if live else None)

    candidates: list = []
    if live is not None and live.exists():
        candidates.append(live)
    if project_dir is not None and project_dir.is_dir():
        others = sorted(
            (p for p in project_dir.glob("*.jsonl") if p != live),
            key=lambda p: p.stat().st_mtime, reverse=True,
        )
        candidates.extend(others)  # 全部走査。 ハード上限 (旧 40 / 拡張 200) は長期 cwd で
        # 「祖先 uuid が範囲外」 で lineage を中途半端に打ち切る事故の元だったので撤廃。
        # 自然な上限は maintenance.cleanup_old_jsonl (= 14 日 / 500MB 自動掃除) が引いてくれる。

    needle = from_uuid.encode("utf-8")
    src_path = None
    for p in candidates:
        try:
            if needle in p.read_bytes():
                src_path = p
                break
        except OSError:
            continue

    if src_path is None:
        logger.warning(
            "fork: from_uuid not found session=%s uuid=%s scanned=%d dir=%s",
            session_id, from_uuid, len(candidates), project_dir,
        )
        raise HTTPException(
            status_code=404,
            detail="この会話のログに該当メッセージが見つかりません",
        )

    # 第一手: from_uuid を含む jsonl 単体で lineage を組む。 1 jsonl = 1 claude session の
    # 中で会話が閉じてればここで完走する (= ほとんどのケース)。
    # 保険 (lazy stitching): claude が compact / session roll で会話を複数 jsonl に分散させた
    # 場合、 parentUuid 鎖の親が src_path に無い時点で打ち切られる。 そこで「鎖が根 (= parentUuid
    # =null) まで到達したか」 を lineage_root_resolved で確認し、 未到達なら同 cwd の他 jsonl を
    # 新しい順に 1 つずつ追加 load して再試行する。 鎖が完走するか候補が尽きるまで繰り返す。
    # 同 cwd の他セッション jsonl は uuid が独立しているので鎖に紛れ込まず、 余計な読みでも
    # build_forked_lineage の正しさには影響しない (= 安全に lazy で増やせる)。
    source_lines = src_path.read_text(encoding="utf-8").splitlines()
    extra_files = 0
    if project_dir is not None and project_dir.is_dir():
        other_iter = iter(sorted(
            (p for p in project_dir.glob("*.jsonl") if p != src_path),
            key=lambda p: p.stat().st_mtime, reverse=True,
        ))
        while not lineage_root_resolved(source_lines, from_uuid):
            try:
                nxt = next(other_iter)
            except StopIteration:
                break  # もう候補無し = ここまでの鎖で確定
            try:
                source_lines.extend(nxt.read_text(encoding="utf-8").splitlines())
                extra_files += 1
            except OSError:
                continue

    status = fork_point_status(source_lines, from_uuid)
    logger.info(
        "fork: session=%s jsonl=%s from_uuid=%s lines=%d extra_files=%d status=%s",
        session_id, src_path.name, from_uuid, len(source_lines), extra_files, status,
    )
    if status != "ok":
        raise HTTPException(
            status_code=400,
            detail="この位置からは分岐できません (= user 発言か完了したターンのみ)",
        )

    new_claude_id = str(uuid.uuid4())
    try:
        forked = build_forked_lineage(source_lines, from_uuid, new_claude_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    if not forked:
        raise HTTPException(status_code=400, detail="分岐対象の会話が空です")
    logger.info(
        "fork: lineage built session=%s lines=%d -> new_jsonl=%s.jsonl lineage_rows=%d",
        session_id, len(source_lines), new_claude_id, len(forked),
    )

    # 新 jsonl は project dir (= 同 cwd hash) に置く。 新タブは agent を継承 = 同 cwd で spawn
    # するので claude --resume がこの新 jsonl を確実に見つける。
    dest = src_path.parent / f"{new_claude_id}.jsonl"
    atomic_write_text(dest, "\n".join(forked) + "\n")

    new_meta = register_session(
        parent.agent_id,
        title=f"{parent.title} fork",
        parent_id=session_id,
        resume_session_id=new_claude_id,
    )
    return new_meta.to_dict()


def _mark_user_stopped(session_id: str) -> bool:
    """ユーザ Stop 意思を backend の権威 state に書く。 /views/ws の stop メッセージ
    から呼ばれる (= HTTP POST 経由は廃止、 WebSocket で確実に届ける構造)。"""
    st = stream_states.get(session_id)
    if st is None:
        return False
    st.user_stopped = True
    if st.busy:
        st.busy = False
    sessions_overview.notify()
    return True


@router.post("/sessions/{session_id}/restart")
async def restart_session(session_id: str, _: str = Depends(require_session)):
    """claude プロセスを kill + 新規 spawn する (= /clear と違ってプロセスメモリも完全解放)。
    新 claude_sid に切り替わるが SessionStart hook で bindings 更新されるので、 PWA タブは
    シームレスに続けて使える。 長期稼働で claude プロセスメモリが累積する問題への対策。"""
    from pty_runner import kill_tmux_session, pty_sessions  # noqa: PLC0415
    import jsonl_watcher  # noqa: PLC0415
    from pty_routes import ensure_pty_session_for  # noqa: PLC0415
    # kill 経路は delete_session と同じだが、 sessions_meta は維持して即 spawn し直す
    try:
        kill_tmux_session(session_id)
        pty_sessions.pop(session_id, None)
        jsonl_watcher.unregister(session_id)
    except Exception:
        logger.debug("restart kill phase failed for %s", session_id, exc_info=True)
    # フォーク産タブを通常タブ化する。 restart のセマンティクスは「文脈リセット + プロセス
    # リセット」 で、 fork タブの resume_session_id を残したままだと再 spawn で
    # `claude --resume <同一 id>` が走り、 claude CLI が重複起動を検知して即 exit (rc=0) する
    # = ターミナルが何も変わらず終了しない (2026-06-04 確認)。 fork の親文脈引き継ぎは初回
    # spawn で完了した役目なので、 restart のタイミングで resume_session_id を落として通常
    # タブと完全に同じ launch_alias 起動経路に合流させる。 役目を終えた fork jsonl は同時に
    # 掃除する (= delete_session の GC と同型、 蓄積させない)。 parent_id は派生履歴として
    # 残し、 ドロワー上の親子インデント表示は維持する。
    meta = sessions_meta.get(session_id)
    fork_resume_id = getattr(meta, "resume_session_id", None) if meta is not None else None
    if meta is not None and fork_resume_id:
        meta.resume_session_id = None
        save_sessions_meta()
        try:
            from jsonl_watcher import _cwd_to_project_dir  # noqa: PLC0415
            cwd = (AGENTS.get(meta.agent_id) or {}).get("cwd")
            project_dir = _cwd_to_project_dir(cwd) if cwd else None
            if project_dir is not None:
                fork_jsonl = project_dir / f"{fork_resume_id}.jsonl"
                if fork_jsonl.exists():
                    fork_jsonl.unlink(missing_ok=True)
                    logger.info(
                        "fork: gc jsonl on restart session=%s file=%s",
                        session_id, fork_jsonl.name,
                    )
        except Exception:
            logger.debug("fork jsonl gc on restart failed for %s", session_id, exc_info=True)
    # 新規 spawn (= 同 PWA_SID で tmux 再生成 + claude 再起動 + SessionStart hook で
    # 新 claude_sid を confirm_bind)
    try:
        await ensure_pty_session_for(session_id)
    except Exception:
        logger.exception("restart spawn phase failed for %s", session_id)
        return {"ok": False, "reason": "spawn_failed"}
    # agent_status の進行中フラグをリセット (= 新プロセスなので何も保留してない)
    a = agent_status.get(session_id)
    if a is not None:
        a["current_tool"] = None
        a["pending_question"] = None
        a["pending_plan"] = None
        a["subagent"] = None
        a["plan_mode"] = False
    state = stream_states.get(session_id)
    if state is not None:
        # 新プロセス = 過去の Stop 意思は無効化 (= 残ったまま sticky だと新 turn が永久に
        # busy=false に強制されて停止ボタンが立たない逆方向のバグになる)。
        state.user_stopped = False
        state.status_event.set()
    return {"ok": True}


@router.delete("/sessions/{session_id}")
async def delete_session(session_id: str, _: str = Depends(require_session)):
    # フォーク産タブはここで掴んでおく (= unregister 後だと meta が消えて辿れない)。
    # resume_session_id は build_forked_lineage で書き出した新 jsonl のファイル名。
    meta = sessions_meta.get(session_id)
    fork_resume_id = getattr(meta, "resume_session_id", None) if meta is not None else None
    fork_agent_id = getattr(meta, "agent_id", None) if meta is not None else None
    # PTY + tmux + JSONL binding を一括 cleanup
    try:
        from pty_runner import kill_tmux_session, pty_sessions  # noqa: PLC0415
        import jsonl_watcher  # noqa: PLC0415
        kill_tmux_session(session_id)
        pty_sessions.pop(session_id, None)
        jsonl_watcher.unregister(session_id)
    except Exception:
        logger.debug("session cleanup failed for %s", session_id, exc_info=True)
    # 一時ファイルをクリーンアップ
    for p in session_tmp_files.pop(session_id, []):
        try:
            p.unlink(missing_ok=True)
        except Exception:
            logger.debug("tmp file unlink failed: %s", p, exc_info=True)
    # フォーク産 jsonl の GC: 削除時にこのタブが生成した新 jsonl も消す。
    # build_forked_lineage は parentUuid 鎖を全部新ファイルに書き出す (= 自己完結) ので、
    # 孫フォークがあっても孫の jsonl 単体で resume できる。 親 fork jsonl を消して問題ない。
    # 元タブの jsonl (= claude が普段使ってる alias 起動由来) はここでは絶対に触らない。
    if fork_resume_id and fork_agent_id:
        try:
            from jsonl_watcher import _cwd_to_project_dir  # noqa: PLC0415
            cwd = (AGENTS.get(fork_agent_id) or {}).get("cwd")
            project_dir = _cwd_to_project_dir(cwd) if cwd else None
            if project_dir is not None:
                fork_jsonl = project_dir / f"{fork_resume_id}.jsonl"
                if fork_jsonl.exists():
                    fork_jsonl.unlink(missing_ok=True)
                    logger.info(
                        "fork: gc jsonl session=%s file=%s", session_id, fork_jsonl.name,
                    )
        except Exception:
            logger.debug("fork jsonl gc failed for %s", session_id, exc_info=True)
    unregister_session(session_id)
    return {"status": "ok", "session_id": session_id}


def _build_status(session_id: str) -> dict:
    """/status と /status/.../stream で共有する status payload 生成。

    使用率系 (5h/7d/ctx/model) は proxy を使わず rate-limits.jsonl (= statusline 記録)
    から取る。 取れない項目は従来の shared_status / agent_status に fallback。

    model / ctx は session ごとに違うので、 この pwa session に紐づく claude_sid
    (= 確定 binding の jsonl ファイル名) で rate-limits を絞る。 これでタブ切替時に
    そのタブの最新ステータスラインが出る (= 別タブの値に引っ張られない)。
    """
    a = agent_status[session_id]
    import jsonl_watcher  # noqa: PLC0415
    jp = jsonl_watcher.get_jsonl_for(session_id)
    claude_sid = jp.stem if jp else None
    rl = read_latest_rate_limits(claude_sid)
    return {
        "model": rl.get("model") or a["model"],
        "ctx_pct": rl["context_pct"] if rl.get("context_pct") is not None else a["ctx_pct"],
        "plan_mode": a["plan_mode"],
        "current_tool": a["current_tool"],
        "todos": a["todos"],
        "subagent": a["subagent"],
        "pending_plan": a.get("pending_plan"),
        "pending_question": a.get("pending_question"),
        "five_hour_pct": rl["five_hour_pct"] if rl.get("five_hour_pct") is not None else shared_status["five_hour_pct"],
        "seven_day_pct": rl["seven_day_pct"] if rl.get("seven_day_pct") is not None else shared_status["seven_day_pct"],
        "five_hour_resets_at": rl.get("five_hour_resets_at") or shared_status["five_hour_resets_at"],
        "seven_day_resets_at": rl.get("seven_day_resets_at") or shared_status["seven_day_resets_at"],
        # backend プロセスの起動時刻 (= frontend がこの値の変化で「再起動された」 と検知し、
        # 古い streaming bubble を強制的に停止扱いに固定する)。
        "backend_start_time": backend_start_time,
    }


@router.get("/status/{session_id}")
def get_status(session_id: str, _: str = Depends(require_session)):
    return _build_status(session_id)


@router.get("/status/{session_id}/stream")
async def status_stream(session_id: str, _: str = Depends(require_session)):
    """状態変化を即時 push する SSE。 frontend は EventSource で subscribe して
    polling 撤廃。 state.status_event が set されるたびに最新 status を yield。
    timeout で keep-alive ping、 タブ閉じれば接続が切れて自然終了。"""
    state = stream_states[session_id]

    async def gen():
        # 接続直後に snapshot を 1 chunk で送る (= retry + initial data を結合し、
        # Starlette の小チャンク buffering を回避)。
        initial = f"retry: 3000\n\ndata: {json.dumps(_build_status(session_id))}\n\n"
        yield initial
        while True:
            try:
                # 20 秒待っても変化無ければ keep-alive ping (= proxy idle 切断対策)
                await asyncio.wait_for(state.status_event.wait(), timeout=20.0)
                state.status_event.clear()
                yield f"data: {json.dumps(_build_status(session_id))}\n\n"
            except asyncio.TimeoutError:
                # keep-alive 兼 status 更新: TUI 経路は status_event がほぼ発火しないので、
                # この timeout で rate-limits 込みの最新 status を定期 push する
                # (= 5h/7d を ~20 秒粒度で更新)。
                yield f"data: {json.dumps(_build_status(session_id))}\n\n"

    return StreamingResponse(
        gen(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


def _build_sessions_overview() -> dict:
    """全 session の busy / pending_question を 1 dict で返す (= /sessions/overview/stream payload)。

    busy は monitor_all_sessions_loop が JSONL から算出した backend 権威値 (= chat SSE の
    result 配信に依存しない)。 frontend は各 sid の busy で loading を上書きして、 青丸
    (処理中) / 赤丸 (完了未読) / 停止ボタンを **非アクティブタブでも** live 追従させる。"""
    out: dict[str, dict] = {}
    for sid in list(sessions_meta.keys()):
        st = stream_states.get(sid)
        a = agent_status.get(sid) or {}
        out[sid] = {
            "busy": bool(st.busy) if st is not None else False,
            "pending_question": bool(a.get("pending_question")),
        }
    return out


@router.get("/sessions/overview/stream")
async def sessions_overview_stream():
    """全 session の busy / pending を 1 本で push する SSE (= 案 B)。

    タブごとに SSE を張らず 1 接続で全 session をカバーするので、 session 数が増えても
    接続は 1 本のまま (= リソース増加なし)。 sessions_overview.notify() のたびに最新 snapshot
    を yield。 20 秒の timeout で keep-alive 兼 定期同期。

    接続ごとに専用 Event を購読するので、 複数デバイス同時でも 1 接続の clear() が他接続の
    push を奪わない (= 旧 単一 Event 共有時の取りこぼしを解消)。"""
    async def gen():
        # 接続ごとに専用 Event を購読 (= 複数デバイス同時でも push を取りこぼさない)。
        ev = sessions_overview.subscribe()
        try:
            # 接続直後に snapshot を 1 chunk で送る (= retry + 初期 data を結合)。
            yield f"retry: 3000\n\ndata: {json.dumps(_build_sessions_overview())}\n\n"
            while True:
                try:
                    await asyncio.wait_for(ev.wait(), timeout=20.0)
                    ev.clear()
                    yield f"data: {json.dumps(_build_sessions_overview())}\n\n"
                except asyncio.TimeoutError:
                    yield f"data: {json.dumps(_build_sessions_overview())}\n\n"
        finally:
            sessions_overview.unsubscribe(ev)

    return StreamingResponse(
        gen(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.get("/agents")
def list_agents():
    """セッション作成時の選択肢として agent 種別一覧を返す。"""
    return [
        {"id": name, "display_name": cfg.get("display_name", name.upper())}
        for name, cfg in AGENTS.items()
    ]


# 旧: session 別 model / effort / fast 切替 endpoint (= ⋯ メニューの ModelEffortPicker
# 用)。 2026-05-31 撤去。 設計方針「制御はターミナル」 に揃え、 切替はターミナルから
# `/model <name>` `/effort <level>` `/fast` を直打ちする (= picker で切替えても結局
# 切替確認プロンプトが出てターミナル操作が要る、 多くの場合 default 固定で十分)。


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
    conn_id = uuid.uuid4().hex
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
