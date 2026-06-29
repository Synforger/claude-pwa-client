"""session CRUD + フォーク + リスタート + 削除 (= 旧 chat.py から分割、 backend-F-28 /
crosscut-F-04)。

責務:
- GET    /sessions                        : list
- POST   /sessions                        : 作成
- PATCH  /sessions/{sid}                  : title / notify_mode 変更
- POST   /sessions/{sid}/fork             : フォーク (= jsonl 鎖を新 claude_sid で書き出し)
- POST   /sessions/{sid}/restart          : claude プロセス kill + spawn (= 文脈リセット)
- DELETE /sessions/{sid}                  : 完全削除 + フォーク産 jsonl GC

session メタ / status SSE / accounts は別 module (= overview.py / accounts.py)。
"""
from __future__ import annotations

import logging
import uuid

from fastapi import APIRouter, Body, Depends, HTTPException

from backend import state
from backend.config import AGENTS
from backend.core.fork import build_forked_lineage_lazy, fork_point_status
from backend.jsonl import resolver as jsonl_resolver
from backend.state import (
    atomic_write_text,
    register_session,
    rename_session,
    save_sessions_meta,
    sessions_meta,
    sessions_overview,
    set_notify_mode,
    session_tmp_files,
    stream_states,
    unregister_session,
)
from backend.terminal.runner import kill_tmux_session, pty_sessions
import backend.jsonl.watcher as jsonl_watcher
from backend.jsonl import history as session_history

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
async def create_session(payload: dict = Body(...)):
    from backend.config import ACCOUNTS  # noqa: PLC0415
    agent_id = payload.get("agent_id")
    title = payload.get("title")
    account_id = payload.get("account_id")
    if not agent_id or agent_id not in AGENTS:
        raise HTTPException(status_code=400, detail="agent_id が無効です")
    if account_id is not None and account_id not in ACCOUNTS:
        raise HTTPException(status_code=400, detail="account_id が無効です")
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
async def fork_session(session_id: str, payload: dict = Body(...), _: str = Depends(require_session)):
    """会話を任意メッセージから分岐する (= フォーク)。

    body: {from_uuid}。 from_uuid を leaf に parentUuid 鎖を根まで遡った lineage を、 新しい
    claude session の jsonl として元と同じ project dir に書き出す。 その session を
    `claude --resume` で開く新タブ (= SessionDef、 parent_id + resume_session_id 付き) を
    登録して返す。 元タブ・元 jsonl には一切触れない。
    """
    from_uuid = payload.get("from_uuid")
    if not from_uuid or not isinstance(from_uuid, str):
        raise HTTPException(status_code=400, detail="from_uuid が必要です")

    parent = sessions_meta[session_id]

    # from_uuid を含む jsonl を探す。 claude は途中で session id をロール (= compact / 継続)
    # することがあり、 画面に残る古いメッセージは前のファイルに居る一方、 live binding
    # は今 open 中の新ファイルを返す。 そのため「今のファイルだけ」 でなく同じ cwd の
    # project dir 内の全 jsonl を新しい順に走査して、 uuid を実際に含むファイルを source
    # にする (= uuid は一意なので確実に当たる)。
    live = jsonl_resolver.resolve_jsonl(session_id, prefer="live")
    project_dir = jsonl_resolver.resolve_jsonl(session_id, prefer="project_dir")
    # fork 専用フォールバック: cwd 解決不能でも live があれば「live と同じ dir」 を使う
    # (= 過去 behavior 互換、 resolver 一般 API はこの fallback を持たない)。
    if project_dir is None and live is not None:
        project_dir = live.parent

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

    # まず src_path 単体で fork point の妥当性 (= tool 行で切れてないか) を確認。
    # 大半のフォークは src_path の中で会話が閉じてて、 ここで全部完結する。
    src_lines = src_path.read_text(encoding="utf-8").splitlines()
    status = fork_point_status(src_lines, from_uuid)
    if status != "ok":
        raise HTTPException(
            status_code=400,
            detail="この位置からは分岐できません (= user 発言か完了したターンのみ)",
        )

    # lazy stitching: build_forked_lineage_lazy が鎖を辿りながら、 親 uuid が src_lines に
    # 無い時だけ fetch_more で次の jsonl を 1 個取りに来る。 鎖が src_lines 内で閉じれば
    # 追加 jsonl は読まれない (= 大半のケース)。 同 cwd の他 jsonl は新しい順に提供。
    other_iter = None
    if project_dir is not None and project_dir.is_dir():
        other_iter = iter(sorted(
            (p for p in project_dir.glob("*.jsonl") if p != src_path),
            key=lambda p: p.stat().st_mtime, reverse=True,
        ))
    extra_files: list[str] = []

    def fetch_more():
        if other_iter is None:
            return None
        try:
            nxt = next(other_iter)
        except StopIteration:
            return None
        try:
            lines = nxt.read_text(encoding="utf-8").splitlines()
        except OSError:
            return []  # 1 ファイルだけ読み損ねても次へ進めるよう空 list を返す
        extra_files.append(nxt.name)
        return lines

    new_claude_id = str(uuid.uuid4())
    try:
        forked = build_forked_lineage_lazy(src_lines, from_uuid, new_claude_id, fetch_more)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    if not forked:
        raise HTTPException(status_code=400, detail="分岐対象の会話が空です")
    logger.info(
        "fork: session=%s src=%s from_uuid=%s extra_files=%d -> new_jsonl=%s.jsonl rows=%d",
        session_id, src_path.name, from_uuid, len(extra_files),
        new_claude_id, len(forked),
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
    return new_meta.to_dict()


@router.post("/sessions/{session_id}/restart")
async def restart_session(session_id: str, _: str = Depends(require_session)):
    """claude プロセスを kill + 新規 spawn する (= /clear と違ってプロセスメモリも完全解放)。
    新 claude_sid に切り替わるが SessionStart hook で bindings 更新されるので、 PWA タブは
    シームレスに続けて使える。 長期稼働で claude プロセスメモリが累積する問題への対策。"""
    # kill する前に現 claude_sid を履歴に積む (= 事故時の復旧源、 pwa_sid あたり最新 3 件保持)。
    # binding が落ちてる場合は no-op になる (= record_end が None を弾く)。
    try:
        cur = jsonl_watcher.get_jsonl_for(session_id)
        if cur is not None:
            cur_sid = cur.stem  # claude jsonl ファイル名 = claude_sid
            session_history.record_end(session_id, cur_sid, jsonl_path=str(cur))
    except Exception:
        # 履歴記録の失敗は復旧経路を 1 本失うので、 debug ではなく warning で残す
        # (= 2026-06-22 silent-failure sweep)。
        logger.warning("session_history record failed for %s", session_id, exc_info=True)
    # kill 経路は delete_session と同じだが、 sessions_meta は維持して即 spawn し直す
    try:
        kill_tmux_session(session_id)
        pty_sessions.pop(session_id, None)
        jsonl_watcher.unregister(session_id)
    except Exception:
        # kill 失敗 = claude プロセスが残ったまま spawn する経路に進み二重起動の race を起こす
        # 可能性がある。 warning で残す (= 2026-06-22)。
        logger.warning("restart kill phase failed for %s", session_id, exc_info=True)
    # フォーク産タブを通常タブ化する (= state.demote_fork_to_normal、 backend-F-44)。
    # restart のセマンティクスは「文脈リセット + プロセスリセット」 で、 fork タブの
    # resume_session_id を残したままだと再 spawn で `claude --resume <同一 id>` が走り、
    # claude CLI が重複起動を検知して即 exit (rc=0) する = ターミナルが何も変わらず終了
    # しない (2026-06-04 確認)。 fork の親文脈引き継ぎは初回 spawn で完了した役目なので、
    # restart のタイミングで resume_session_id を落として通常タブと完全に同じ launch_alias
    # 起動経路に合流させる。 役目を終えた fork jsonl は state helper 内で同時に掃除する
    # (= delete_session の GC と同型、 蓄積させない)。 parent_id は派生履歴として残し、
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
    # agent_status の進行中フラグをリセット (= 新プロセスなので何も保留してない)。
    # SessionState.lock 経由で複数 mutate を 1 critical section に束ねる (= backend-F-07)。
    sess = state.get_session(session_id)
    if sess is not None:
        async with sess.lock:
            a = sess.status
            a["current_tool"] = None
            a["pending_question"] = None
            a["pending_plan"] = None
            a["subagent"] = None
            a["plan_mode"] = False
            # 新プロセス = 過去の Stop 意思は無効化 (= 残ったまま sticky だと新 turn が永久に
            # busy=false に強制されて停止ボタンが立たない逆方向のバグになる)。
            sess.stream.user_stopped = False
            sess.stream.status_event.set()
    # 全 sid SSE (/sessions/status/stream) にも変化を伝える (= per-sid と整合)
    sessions_overview.notify()
    return {"ok": True}


@router.get("/sessions/{session_id}/history")
async def get_session_history(session_id: str, _: str = Depends(require_session)):
    """pwa_sid の直近 claude_sid 履歴 (= 最新 3 件、 新しい順) を返す。 restart 直前に
    記録された claude_sid + ended_at + jsonl_path を持つ。 binding が事故で消えた時の
    復旧 UI 用 (= backend ログ grep より速く前 sid に辿れる経路)。"""
    return {"entries": session_history.get(session_id)}


@router.delete("/sessions/{session_id}")
async def delete_session(session_id: str, _: str = Depends(require_session)):
    # フォーク産タブはここで掴んでおく (= unregister 後だと meta が消えて辿れない)。
    # resume_session_id は build_forked_lineage で書き出した新 jsonl のファイル名。
    meta = sessions_meta.get(session_id)
    fork_resume_id = getattr(meta, "resume_session_id", None) if meta is not None else None
    fork_agent_id = getattr(meta, "agent_id", None) if meta is not None else None
    # PTY + tmux + JSONL binding を一括 cleanup
    try:
        kill_tmux_session(session_id)
        pty_sessions.pop(session_id, None)
        jsonl_watcher.unregister(session_id)
    except Exception:
        # delete 経路の kill 失敗 = backend に session が残るゴースト化の原因。 warning で
        # 残す (= 2026-06-22)。
        logger.warning("session cleanup failed for %s", session_id, exc_info=True)
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
            cwd = (AGENTS.get(fork_agent_id) or {}).get("cwd")
            # module-attribute lookup で monkeypatch 互換維持 (= test が
            # `monkeypatch.setattr(jsonl_watcher, "_cwd_to_project_dir", ...)` する)。
            project_dir = jsonl_watcher._cwd_to_project_dir(cwd) if cwd else None
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


# 旧: session 別 model / effort / fast 切替 endpoint (= ⋯ メニューの ModelEffortPicker
# 用)。 2026-05-31 撤去。 設計方針「制御はターミナル」 に揃え、 切替はターミナルから
# `/model <name>` `/effort <level>` `/fast` を直打ちする (= picker で切替えても結局
# 切替確認プロンプトが出てターミナル操作が要る、 多くの場合 default 固定で十分)。
