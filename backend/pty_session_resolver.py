"""PWA session_id から PTY spawn パラメータ (cwd / launch alias / autoresume) を解決する。

`pty_routes` から呼ばれる。 旧実装は pty_routes.py 内に同居していたが、 「session 設定の解決」
は endpoint 経路 / 送信確認とは独立した責務なので分離した。

主要 API:
    ensure_pty_session_for(session_id) — 必要なら spawn し PtySession を pty_sessions に登録
    resolve_launch_alias(session_id)   — 初回 zsh prompt に送る起動コマンド (alias or claude --resume)
    resolve_autoresume_fallback(sid)   — autoresume が即 exit した時 watchdog が打ち直す通常 alias
"""
from __future__ import annotations

import logging
import shlex
import time
from pathlib import Path

from config import AGENTS, CLAUDE_PATH
from pty_runner import has_tmux_session, pty_sessions, spawn_pty_session
from state import sessions_meta

logger = logging.getLogger(__name__)

# Mac / backend 再起動跨ぎで前回 claude session を自動 resume する時の鮮度上限。
# これより古い jsonl は「もう死んだ会話」 扱いで resume せず通常起動に倒す (= 衛生面)。
AUTORESUME_MAX_AGE_DAYS = 30


def resolve_agent_cfg(session_id: str) -> dict | None:
    """session_id から AGENTS の cfg dict を解決する (= cwd と launch_alias の共通解決)。"""
    cfg = AGENTS.get(session_id)
    if cfg:
        return cfg
    meta = sessions_meta.get(session_id)
    if meta is not None:
        return AGENTS.get(meta.agent_id)
    return None


def resolve_cwd(session_id: str) -> str | None:
    """session_id から起動 cwd を解決する。

    優先順:
        1. session_id がそのまま AGENTS の key (= 直リンク `?terminal=agent_a` 等)
        2. session_id が sessions_meta に登録済なら、 そこに紐付く agent_id 経由で
           AGENTS から取得 (= UI でセッションタブを作る通常経路)
        3. どちらも該当なし → None (= backend の起動 cwd で zsh が立ち上がる)
    """
    cfg = resolve_agent_cfg(session_id)
    return cfg.get("cwd") if cfg else None


def last_resumable_claude_sid(session_id: str) -> str | None:
    """PWA タブの最終 claude session_id を bindings から引いて autoresume 可否を判定する。

    Mac 再起動跨ぎで tmux server が消えると、 backend は spawn 時に新規 tmux + 新規 claude
    を立ち上げる。 そのまま放置だと前回の会話が失われるので、 bindings に confirmed として
    残ってる最後の claude_sid を返して呼び出し側で `claude --resume <id>` させる。

    None を返す条件:
      - bindings に該当タブの entry が無い / confirmed=false
      - jsonl ファイルが消えている (= claude 側 cleanup / 手動削除)
      - jsonl の最終更新が AUTORESUME_MAX_AGE_DAYS より古い (= 死んだ会話)
    """
    try:
        import jsonl_watcher  # noqa: PLC0415
        info = jsonl_watcher.list_bindings().get(session_id)
    except Exception:
        logger.exception("autoresume lookup failed session=%s", session_id)
        return None
    if not info or not info.get("confirmed"):
        return None
    jsonl_path = info.get("jsonl_path")
    if not jsonl_path:
        return None
    p = Path(jsonl_path)
    if not p.is_file():
        return None
    if time.time() - p.stat().st_mtime > AUTORESUME_MAX_AGE_DAYS * 86400:
        return None
    return p.stem


def resolve_launch_alias(session_id: str) -> str | None:
    """初回 spawn で zsh prompt に送る起動コマンドを解決する。

    通常タブは agent cfg の `launch_alias` (= ユーザの claude 起動 wrapper)。 フォークタブ
    (= SessionDef.resume_session_id を持つ) は wrapper でなく `claude --resume <id>` を直接
    送り、 分岐元から書き出した jsonl をその時点の会話として開く。 cwd は agent 継承 (=
    親と同じ project dir) なので resume が新 jsonl を確実に見つける。

    Mac / backend 再起動跨ぎで bindings に前回の claude_sid が残っていれば `claude --resume
    <id>` を返して autoresume を試みる。 即 exit で失敗した場合の fallback は spawn_pty_session
    側の watchdog (= claude プロセスが時間内に検出されなければ通常 alias を打ち直す) で吸収する。
    zsh の `|| alias` で繋ぐと `claude --resume` が rc=0 で即 exit するパターン (= フォーク
    resume と同型の罠) で右辺が走らず zsh プロンプトに残るので使わない。
    """
    meta = sessions_meta.get(session_id)
    resume_id = getattr(meta, "resume_session_id", None) if meta is not None else None
    if resume_id:
        if not CLAUDE_PATH:
            logger.error("fork spawn needs claude_path but it is empty session=%s", session_id)
            return None
        return f"{shlex.quote(CLAUDE_PATH)} --resume {shlex.quote(resume_id)}"
    cfg = resolve_agent_cfg(session_id) or {}
    alias = cfg.get("launch_alias")
    autoresume_id = last_resumable_claude_sid(session_id)
    if autoresume_id and alias and CLAUDE_PATH:
        return f"{shlex.quote(CLAUDE_PATH)} --resume {shlex.quote(autoresume_id)}"
    return alias


def resolve_autoresume_fallback(session_id: str) -> str | None:
    """autoresume が即 exit した時に投入する通常 alias を返す (= 失敗時 fallback)。

    `resolve_launch_alias` が autoresume 用の `claude --resume <id>` を返したケースに限り、
    その失敗時にこの alias を打ち直して通常起動に倒す。 autoresume 経路でない (= 元から alias)
    やフォーク resume (= 意図的分岐) では fallback 不要なので None。
    """
    meta = sessions_meta.get(session_id)
    if meta is not None and getattr(meta, "resume_session_id", None):
        return None
    if last_resumable_claude_sid(session_id) is None:
        return None
    cfg = resolve_agent_cfg(session_id) or {}
    return cfg.get("launch_alias")


async def ensure_pty_session_for(session_id: str) -> None:
    """指定 session の tmux + claude を起動 (既にあれば何もしない)。

    `/ws/pty/{sid}` (= ターミナル画面) 経由だけでなく、 `/jsonl/stream/{sid}`
    (= チャット画面) からも呼ぶことで、 ターミナル画面を一度も開いていないタブでも
    claude が立ち上がって JSONL が作られるようにする。
    """
    existing = pty_sessions.get(session_id)
    if existing is not None and not existing.exit_event.is_set():
        return
    if has_tmux_session(session_id):
        # tmux session は生きてるが backend 側に PtySession 記録が無い (= backend 再起動跨ぎ)。
        # チャット画面側からは attach の必要なし。 JSONL は claude プロセスが書き続けてるので
        # 解決経路 (= jsonl_path_for_session) が拾える。 spawn 重複も避ける
        return
    cfg = resolve_agent_cfg(session_id) or {}
    cwd = cfg.get("cwd")
    launch_alias = resolve_launch_alias(session_id)
    fallback_alias = resolve_autoresume_fallback(session_id)
    try:
        session = await spawn_pty_session(
            session_id, cwd=cwd, launch_alias=launch_alias,
            fallback_alias=fallback_alias,
        )
    except Exception:
        logger.exception("ensure_pty_session_for: spawn failed session=%s", session_id)
        return
    pty_sessions[session_id] = session
