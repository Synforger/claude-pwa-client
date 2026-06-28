"""WebSocket endpoint for the PTY runner (= phase 1 PTY 経路、 旧 SDK 経路と共存)。

Wire protocol (= xterm.js に直接食わせる前提):
    Server → Client:
        - binary frame: PTY 子プロセスからの raw stdout バイト列。
          そのまま xterm.write() に渡すと ANSI 含めて render される。
    Client → Server:
        - binary frame: user 入力 (= stdin に流すバイト列、 keystroke そのまま)。
        - text frame (JSON): control message。
            {"type": "resize", "rows": <int>, "cols": <int>}

接続契機:
    - 新規 session_id: claude プロセスを spawn して PtySession を作る
    - 既存 session_id (= 生存中): 既存セッションに再アタッチ、 過去出力は queue 残量分が即流れる
    - 既存 session_id (= exit 済): 新規 spawn し直し
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import time
import uuid as _uuid_mod
from datetime import datetime, timezone

from fastapi import APIRouter, Body, File, Form, HTTPException, UploadFile, WebSocket, WebSocketDisconnect
from starlette.websockets import WebSocketState

from backend.chat_content import save_to_tmp
from backend.config import AGENTS, CLAUDE_PATH  # noqa: F401  (CLAUDE_PATH は tests monkeypatch 用 re-export)

from backend.terminal.runner import (
    PtySession,
    has_tmux_session,
    jsonl_path_for_session,
    pty_sessions,
    resize_pty,
    spawn_pty_session,
    tmux_send_keys,
    write_pty,
)
from backend.state import sessions_meta

# 送信確認 (= JSONL カウント + wait + 救済再送) は pty_confirm に分離。
# session 解決 + spawn は pty_session_resolver に分離。 ここは endpoint と pump のみ持つ。
from backend.terminal.confirm import (
    _confirm_after_send,
    _count_command_lines,
    _count_in_lines,
    _count_user_prompts,
    _delivery_counter,
    _is_command_line,
    _is_plain_user_prompt,
    _wait_count_added,
)
from backend.terminal.session_resolver import (
    AUTORESUME_MAX_AGE_DAYS as _AUTORESUME_MAX_AGE_DAYS,
    ensure_pty_session_for,
    last_resumable_claude_sid as _last_resumable_claude_sid,
    resolve_agent_cfg as _resolve_agent_cfg,
    resolve_autoresume_fallback as _resolve_autoresume_fallback,
    resolve_cwd as _resolve_cwd,
    resolve_launch_alias as _resolve_launch_alias,
)

logger = logging.getLogger(__name__)
router = APIRouter()




@router.websocket("/ws/pty/{session_id}")
async def pty_socket(ws: WebSocket, session_id: str) -> None:
    await ws.accept()
    # 未知 session_id を弾く (= 任意 sid で backend cwd の zsh を起こさない)。
    if session_id not in AGENTS and session_id not in sessions_meta:
        await ws.send_text(json.dumps({"type": "error", "message": "unknown session"}))
        await ws.close(code=4004, reason="unknown session")
        return

    # scrollback の自動復元は無効化 (= 2026-05-21 再試行で描画破綻、 旧症状再発)。
    # capture-pane の history を流すと、 中に含まれる ANSI cursor 制御 (= claude
    # streaming 中の途中再描画指示等) が新接続側の状態と整合せず画面が壊れる。

    session = pty_sessions.get(session_id)
    if session is None or session.exit_event.is_set():
        # backend 再起動跨ぎ: in-memory PtySession は空でも tmux server には pwa-<sid> が
        # 生き残ってる場合がある (= 既存 claude TUI が継続中)。 そのまま autoresume の
        # launch_alias / fallback_alias を渡して spawn すると、 spawn_pty_session 内の
        # is_new_tmux_session 判定が race / 失敗で True に倒れた時に、 既存 claude TUI に
        # `claude --resume <id>` という文字列がそのまま入力されて pane を乗っ取り、
        # 元の会話が別 jsonl に切り替わる事故が起きる (= 2026-06-08 REDACTEDタブ事故の直接原因)。
        # 既存 tmux にぶら下がるだけの再 attach では絶対に alias を投入しないよう、
        # ここで明示的に None を渡す (= ensure_pty_session_for は has_tmux_session で早期
        # return するので alias 投入経路自体を踏まない、 こちらはそれと整合する経路)。
        tmux_alive = has_tmux_session(session_id)
        cfg = _resolve_agent_cfg(session_id) or {}
        cwd = cfg.get("cwd")
        if tmux_alive:
            launch_alias = None
            fallback_alias = None
        else:
            launch_alias = _resolve_launch_alias(session_id)
            fallback_alias = _resolve_autoresume_fallback(session_id)
        try:
            from backend.config import ACCOUNTS  # noqa: PLC0415
            meta = sessions_meta.get(session_id)
            acct_env = (ACCOUNTS.get(meta.account_id) or {}).get("env") if meta and meta.account_id else None
            # agent cfg.env (= 旧経路、 共有 env) と account.env (= タブ毎) をマージ。 account 優先
            agent_env = cfg.get("env") if isinstance(cfg.get("env"), dict) else {}
            extra_env = {**agent_env, **(acct_env or {})} if (agent_env or acct_env) else None
            session = await spawn_pty_session(
                session_id, cwd=cwd, launch_alias=launch_alias,
                fallback_alias=fallback_alias,
                extra_env=extra_env,
            )
        except Exception as e:
            logger.exception("PTY spawn failed session=%s", session_id)
            try:
                await ws.send_text(json.dumps({"type": "error", "message": str(e)}))
            finally:
                await ws.close(code=4002, reason="spawn failed")
            return
        pty_sessions[session_id] = session

    # 切断中に session.output_queue へ溜まった backlog (= claude TUI のヘッダ定期
    # redraw / カーソル点滅等の incremental refresh) を捨てる。 そのまま流すと
    # 再接続後の xterm に「同じ画面が 2-3 回重なる」 描画事故になる (= 2026-06-12 報告)。
    # 復元は client 側の Ctrl-L 送信で TUI に最新画面を 1 度だけ描かせる経路に任せる。
    drained = 0
    while not session.output_queue.empty():
        try:
            session.output_queue.get_nowait()
            drained += 1
        except asyncio.QueueEmpty:
            break
    if drained:
        logger.info("pty_socket: drained %d backlog chunks before pump session=%s", drained, session_id)

    pump_out = asyncio.create_task(_pump_to_client(ws, session))
    pump_in = asyncio.create_task(_pump_from_client(ws, session))

    done, pending = await asyncio.wait(
        [pump_out, pump_in],
        return_when=asyncio.FIRST_COMPLETED,
    )
    for task in pending:
        task.cancel()
        try:
            await task
        except (asyncio.CancelledError, Exception):
            # benign: WS pump teardown — cancellation is the expected outcome and any
            # straggling exception from the cancelled coroutine is irrelevant after close.
            pass
    # 子プロセスは閉じない (= 再接続できるよう生かしておく、 idle GC は別途)
    try:
        await ws.close()
    except Exception:
        # benign: ws.close() can race with the peer hangup; either way the socket ends up
        # closed, so we don't escalate this into the connection lifecycle.
        pass


async def _pump_to_client(ws: WebSocket, session: PtySession) -> None:
    """PTY 出力 queue → client へバイナリで流す。

    backend-F-15: 旧版は `wait_for(queue.get(), timeout=0.5)` で 0.5s ごとに wake up
    する polling 経路で、 idle 時にも CPU を浪費し、 さらに「子 exit を 0.5s 遅れて検知
    する」 タイムラグもあった。 asyncio.wait(FIRST_COMPLETED) で queue.get と
    exit_event.wait を並走させ、 idle wake-up 0 / exit 検知ゼロ遅延に変える。
    backend-F-26: WS 切断後の send は starlette が "Unexpected ASGI message
    'websocket.send'" の RuntimeError を投げる。 それだけ debug、 他の RuntimeError は
    exception で残す (= 旧版は全部 debug で潰してたので別の RuntimeError も静かに死んでた)。
    """
    queue_task: asyncio.Task | None = None
    exit_task: asyncio.Task | None = None
    try:
        while True:
            if ws.client_state != WebSocketState.CONNECTED:
                return
            if session.exit_event.is_set() and session.output_queue.empty():
                try:
                    await ws.send_text(json.dumps({
                        "type": "exit",
                        "returncode": session.process.returncode,
                    }))
                except (WebSocketDisconnect, RuntimeError):
                    # benign: peer already gone or asgi raised "Unexpected ASGI message" —
                    # we are about to return anyway, so swallowing keeps shutdown clean.
                    pass
                return
            # queue / exit のどちらか先着で wake up (= F-15)。 タスクは再利用せず毎回作る
            # (= asyncio.Queue.get / Event.wait は cancel 可、 cancel コストは無視できる)。
            queue_task = asyncio.create_task(session.output_queue.get())
            exit_task = asyncio.create_task(session.exit_event.wait())
            done, pending = await asyncio.wait(
                [queue_task, exit_task],
                return_when=asyncio.FIRST_COMPLETED,
            )
            for t in pending:
                t.cancel()
            if queue_task in done:
                try:
                    data = queue_task.result()
                except Exception:
                    continue
                await ws.send_bytes(data)
            # exit_task が先着なら次 iter で exit_event/empty 判定に流す
            queue_task = None
            exit_task = None
    except WebSocketDisconnect:
        return
    except RuntimeError as e:
        if "Unexpected ASGI message" in str(e):
            # 既知の WS 切断後 send race (= 2026-05-28 に 8 回以上ログ噴いた汚染源)。 debug で静かに。
            logger.debug("_pump_to_client: ws closed mid-send session=%s: %s", session.session_id, e)
            return
        # 別 RuntimeError は埋もれさせない (= 黙殺で別 bug を見落とすのを防ぐ、 F-26)
        logger.exception("_pump_to_client unexpected RuntimeError session=%s", session.session_id)
    except Exception:
        logger.exception("_pump_to_client error session=%s", session.session_id)
    finally:
        for t in (queue_task, exit_task):
            if t is not None and not t.done():
                t.cancel()


async def _pump_from_client(ws: WebSocket, session: PtySession) -> None:
    """client 入力 → PTY stdin / control。"""
    try:
        while True:
            msg = await ws.receive()
            # FastAPI WebSocket は dict で {"type": "websocket.disconnect" | "websocket.receive", ...}
            if msg.get("type") == "websocket.disconnect":
                return
            data = msg.get("bytes")
            if data:
                write_pty(session, data)
                continue
            text = msg.get("text")
            if text:
                try:
                    ctrl = json.loads(text)
                except json.JSONDecodeError:
                    continue
                if ctrl.get("type") == "resize":
                    resize_pty(
                        session,
                        int(ctrl.get("rows", 40)),
                        int(ctrl.get("cols", 120)),
                    )
                elif ctrl.get("type") == "input":
                    # debug / fallback 経路 (= バイナリが使えない client 用)
                    payload = ctrl.get("data", "")
                    if isinstance(payload, str):
                        write_pty(session, payload.encode("utf-8"))
                else:
                    # 純粋 reply 系 (= ping → pong 等) は handle_text_control に集約、 副作用を伴わない
                    # control message を pure 関数で扱えるようにする (= unit test しやすい、 ADR-013)。
                    reply = handle_text_control(ctrl)
                    if reply is not None:
                        await ws.send_text(json.dumps(reply))
    except WebSocketDisconnect:
        return
    except Exception:
        logger.exception("_pump_from_client error session=%s", session.session_id)


def handle_text_control(ctrl: dict) -> dict | None:
    """副作用なし WS text control を解釈し、 send back する dict を返す (= 不要なら None)。

    現状の対応:
        - {"type": "ping", "ts": <int>}  →  {"type": "pong", "ts": <ts>}  (= ADR-013 heartbeat、
          frontend transport/ws-pty.ts が 25s 間隔で送る ping に即返、 60s pong 不在で frontend が
          force reconnect する設計の対の半分)

    resize / input は PTY 副作用を伴うので呼び出し側で扱う、 ここには載せない。
    """
    if not isinstance(ctrl, dict):
        return None
    t = ctrl.get("type")
    if t == "ping":
        return {"type": "pong", "ts": ctrl.get("ts")}
    return None


def _e2e_inject_user_row(session_id: str, text: str) -> dict:
    """ADR-021 e2e mode helper: synthesize a server-stamped `user` row directly
    into the bound JSONL file. The watcher's tail loop picks it up and the
    unified SSE pump delivers a `user_message` event, exercising the same
    reconcileUserMessage path the real-world tmux send-keys roundtrip would.
    """
    jsonl_path = jsonl_path_for_session(session_id)
    if jsonl_path is None:
        raise HTTPException(status_code=409, detail="no binding for session (= seed missing?)")
    user_uuid = str(_uuid_mod.uuid4())
    ts = datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")
    row = {
        "type": "user",
        "uuid": user_uuid,
        "message": {"role": "user", "content": text},
        "timestamp": ts,
    }
    jsonl_path.parent.mkdir(parents=True, exist_ok=True)
    with jsonl_path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")
    return {"ok": True, "uuid": user_uuid, "e2e": True}


def _require_session(session_id: str) -> None:
    """未知の session_id を弾く (= 任意 sid で新 PTY 起動 / send を許さない)。

    AGENTS の直リンク or sessions_meta 登録のどちらかに居ることを要求。 これがないと
    tailnet 内の誰でも適当な session_id を投げて backend 自身の cwd で zsh を起こせる。
    """
    if session_id in AGENTS:
        return
    if session_id in sessions_meta:
        return
    raise HTTPException(status_code=404, detail="Unknown session")


@router.post("/pty/{session_id}/send")
async def pty_send(session_id: str, payload: dict = Body(...)) -> dict:
    """chat UI からの入力を tmux session に送る (= send-keys 経路、 PTY attach 不要)。

    送信本文 (= text + enter) の場合は、 JSONL に user 行が +1 されるかを最大 2s
    監視して機械的に送信成功を確認する。 +1 されなければ 1 回だけ再送して +1.5s 待つ。
    確認できなければ ok=False で返し、 frontend に「届かなかった」 ことを通知する
    (= メッセージボックスに text を残して再送できるようにする経路)。

    ADR-021 (CPC_E2E=1): bypass tmux send-keys entirely - the e2e harness has
    no real tmux session / claude process, so we synthesize a server-stamped
    `user` JSONL row directly. The watcher's tail loop picks it up and the
    unified SSE delivers a user_message event, matching the real-world shape
    that reconcileUserMessage was written for.

    payload:
        text  (str, optional): literal 文字列 (= プロンプト本文)
        key   (str, optional): tmux キー名 (= "Escape" で停止、 "C-c" 等)
        enter (bool, optional): 末尾に Enter (= 確定)
    """
    _require_session(session_id)
    text = payload.get("text")
    key = payload.get("key")
    enter = bool(payload.get("enter", False))

    if os.environ.get("CPC_E2E") == "1" and text and enter:
        return _e2e_inject_user_row(session_id, text)

    # 確認対象は「ユーザ送信本文」 = text あり + enter ありのケースのみ。
    # 自由記述以外のキー送信 (Escape 等)、 AskUserQuestion 自由記述の 1 回目 (typeNum、 enter なし)
    # 等は確認しない (= 送信完了の概念がない、 or 別経路で確認)。
    confirm = bool(text) and enter
    # slash command (= /deep-research 等) は素プロンプト行を作らず `<command-name>` の
    # harness XML 行を作るので確認カウンタを切り替える。
    _, is_slash = _delivery_counter(text or "")
    initial_pos = 0
    jsonl_path = None
    if confirm:
        jsonl_path = jsonl_path_for_session(session_id)
        if jsonl_path is not None:
            # 送信直前の file size を境界に取り、 確認 wait はそこからの差分行だけ読む
            try:
                initial_pos = jsonl_path.stat().st_size
            except OSError:
                initial_pos = 0
    ok = tmux_send_keys(session_id, text=text, key=key, enter=enter)
    if not ok or not confirm or jsonl_path is None:
        return {"ok": ok}
    return await _confirm_after_send(session_id, text, jsonl_path, initial_pos, is_slash)


@router.post("/pty/{session_id}/send-with-files")
async def pty_send_with_files(
    session_id: str,
    text: str = Form(default=""),
    files: list[UploadFile] = File(default=[]),
) -> dict:
    """添付ファイル付きで text を tmux session に送る。 file は uploads/tmp に保存して
    保存先 path を本文末尾に追記する形で claude に投入する (= claude が Read tool で
    自分で読む経路、 旧 SDK 経路の base64 image 同梱と違って tmux 打鍵が軽い)。

    payload (multipart/form-data):
        text  (str):              本文
        files (list[UploadFile]): 添付ファイル群 (画像 / テキスト / その他何でも)
    """
    _require_session(session_id)
    saved = await save_to_tmp(files, session_id)
    parts: list[str] = []
    if text.strip():
        parts.append(text.strip())
    if saved:
        # 改行込みの本文を tmux send-keys に渡すと claude の入力欄で意図せぬ確定が起きうるので
        # 1 行に押し込む (= 「[添付ファイル: /path/to/a, /path/to/b]」)。 path に空白は入らない
        # 前提 (= chat_content.save_to_tmp が uuid.hex + 元拡張子で命名するので安全)。
        paths = ", ".join(s["path"] for s in saved)
        parts.append(f"[添付ファイル: {paths}]")
    full_text = " ".join(parts)
    if not full_text:
        return {"ok": False, "reason": "empty"}
    saved_files = [{"name": s["name"], "path": s["path"]} for s in saved]
    # text 経路と同じ確認 + Enter 追い打ち救済を効かせる。 添付経路は本文が長く (= path 付き)
    # `paste again to expand` で Enter が吸われやすく、 旧実装は単発送信で確認も救済も無かった
    # ため「ターミナルに移動して手で Enter」 が必要だった。
    _, is_slash = _delivery_counter(full_text)
    jsonl_path = jsonl_path_for_session(session_id)
    initial_pos = 0
    if jsonl_path is not None:
        try:
            initial_pos = jsonl_path.stat().st_size
        except OSError:
            initial_pos = 0
    ok = tmux_send_keys(session_id, text=full_text, enter=True)
    if not ok or jsonl_path is None:
        return {"ok": ok, "saved_files": saved_files}
    result = await _confirm_after_send(
        session_id, full_text, jsonl_path, initial_pos, is_slash
    )
    result["saved_files"] = saved_files
    return result


