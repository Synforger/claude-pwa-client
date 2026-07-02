"""ホームディレクトリ配下のファイル閲覧・編集 / ディレクトリツリー取得。

セキュリティ: tailnet 経由で誰でも `/file` を叩けるので、 秘密ファイル (= SSH 鍵 / クラウド
認証情報 / シェル初期化ファイル) は読み書き両方禁止。 HOME 配下 deny list ベース。
"""
import logging
import os
import re
from pathlib import Path

from fastapi import APIRouter, Body, HTTPException, Query

from backend.config import FILE_SIZE_LIMIT, HOME
from backend.errors import raise_error

logger = logging.getLogger(__name__)
router = APIRouter()


# 読み書きを完全に禁止するパス / 拡張子 / ファイル名のパターン。 HOME 配下に存在しても
# `/file` 経由では到達させない。 リモートシェル奪取 / 認証情報漏洩経路を物理的に塞ぐ。
_DENY_RE = re.compile(
    r"(?:^|/)(?:"
    r"\.ssh|\.aws|\.gnupg|\.kube|\.docker|\.config/gh|\.netrc|"
    r"\.zshrc|\.zshenv|\.zprofile|\.bashrc|\.bash_profile|\.profile|"
    r"\.zsh_history|\.bash_history"
    r")(?:$|/)"
    r"|(?:^|/)(?:authorized_keys|id_rsa|id_ed25519|id_ecdsa|id_dsa|known_hosts)$"
    r"|\.(?:pem|key|p12|pfx)$"
)


def _resolve_safe(path_str: str) -> Path:
    resolved = Path(path_str).expanduser().resolve()
    # HOME 配下 (= 物理的に許可された roots) の境界チェック。 symlink は resolve() で展開済。
    try:
        resolved.relative_to(HOME)
    except ValueError:
        raise HTTPException(status_code=403, detail="Access denied")
    # 秘密ファイル deny list。 SSH 鍵 / 認証情報 / シェル初期化ファイル等は読み書き不可。
    if _DENY_RE.search(str(resolved)):
        raise HTTPException(status_code=403, detail="Access denied")
    return resolved


@router.get("/file")
def get_file(path: str = Query(...)):
    resolved = _resolve_safe(path)
    if not resolved.exists():
        raise HTTPException(status_code=404, detail="File not found")
    if not resolved.is_file():
        raise HTTPException(status_code=400, detail="Not a file")
    if resolved.stat().st_size > FILE_SIZE_LIMIT:
        raise_error(413, "file_too_large", "ファイルが大きすぎます（上限 1MB）", limit="1MB")
    try:
        content = resolved.read_text(errors="replace")
    except Exception:
        # exception message にファイルパスや OS error が露出しないよう汎用 detail に統一。
        # 詳細は server log に残るので運用時の調査はそちらで。
        logger.exception("failed to read file: %s", resolved)
        raise HTTPException(status_code=500, detail="Internal error")
    return {"path": str(resolved), "content": content}


@router.put("/file")
def put_file(path: str = Body(...), content: str = Body(...)):
    resolved = _resolve_safe(path)
    if resolved.exists() and not resolved.is_file():
        raise HTTPException(status_code=400, detail="Not a file")
    # 書き込みサイズも GET と同じ上限で塞ぐ。 これがないと tailnet 内ユーザが HOME 配下の
    # 任意ファイルに数 GB 書いて disk を枯渇させられる。
    if len(content.encode("utf-8")) > FILE_SIZE_LIMIT:
        raise_error(413, "file_too_large", "ファイルが大きすぎます（上限 1MB）", limit="1MB")
    try:
        resolved.write_text(content, encoding="utf-8")
    except Exception:
        logger.exception("failed to write file: %s", resolved)
        raise HTTPException(status_code=500, detail="Internal error")
    return {"ok": True}


# background task の出力ログ (= `<task-notification>` の output-file)。 harness が
# `REDACTED_PATH/<project>/<session>/tasks/<task-id>.output` に書く一時ファイルで
# HOME の外にあるため `/file` (= HOME 限定) では読めない。 この狭いパターンだけ通す専用経路。
# resolve() で `..` / symlink を展開した後の絶対パスを再検査して traversal を物理的に塞ぐ。
# macOS は resolve() で /tmp → /private/tmp に展開、 Linux (WSL2) は /tmp のまま。 両対応で
# 先頭 /private を任意にする。
_TASK_OUTPUT_RE = re.compile(
    r"^/(?:private/)?tmp/claude-\d+/[^/]+/[^/]+/tasks/[A-Za-z0-9._-]+\.output$"
)


def _is_subagent_jsonl(resolved: Path) -> bool:
    """resolve() 済 path が `~/.claude/projects/<project>/<claude_sid>/subagents/[workflows/<runId>/]?agent-<id>.jsonl`
    (= Claude Code が subagent 実行時に生成する構造化 transcript) の実体を指しているか。

    Claude Code 側の仕様変化で `<task-notification>` の output-file が `/tmp/.../tasks/<id>.output`
    ではなく上記 jsonl への symlink になった (= 2026-07 頃観測)。 `_TASK_OUTPUT_RE` は
    /tmp 直系のパターンしか通さないので、 resolve() 後の実体が jsonl の場合に 403 を返して
    frontend の TaskNotification 展開が「出力を読めませんでした 403」 で固まる。 symlink 先が
    Claude 自身が書いた jsonl であることを構造で認めて許可する。 stat().st_uid == getuid() の
    UID 一致 check は既存を維持するので、 攻撃者制御 symlink での外部 file 読取は依然塞がる。"""
    try:
        claude_projects = (HOME / ".claude" / "projects").resolve()
    except OSError:
        return False
    try:
        rel = resolved.relative_to(claude_projects)
    except ValueError:
        return False
    if "subagents" not in rel.parts:
        return False
    return resolved.name.startswith("agent-") and resolved.suffix == ".jsonl"


def _resolve_task_output_path(path: str) -> Path:
    """/task-output と /task-transcript 共通の path 検証。 resolve() 後の絶対 path が
    task-output regex (= /tmp/claude-.../tasks/*.output) OR subagent jsonl symlink target
    にマッチすること + 実在 + is_file + UID 一致 の 4 条件を満たすものだけ通す。 それ以外は
    403 / 404 / 400 を raise する。"""
    resolved = Path(path).expanduser().resolve()
    if not (_TASK_OUTPUT_RE.match(str(resolved)) or _is_subagent_jsonl(resolved)):
        raise HTTPException(status_code=403, detail="Access denied")
    if not resolved.exists():
        raise HTTPException(status_code=404, detail="File not found")
    if not resolved.is_file():
        raise HTTPException(status_code=400, detail="Not a file")
    # /tmp は OS 共有領域なので、 自分が起動した claude プロセスが書いたファイルだけ通す
    # (= 別ユーザ / 攻撃者制御のシンボリックリンクを介した読み取りを塞ぐ)。
    if resolved.stat().st_uid != os.getuid():
        raise HTTPException(status_code=403, detail="Access denied")
    return resolved


@router.get("/task-output")
def get_task_output(path: str = Query(...)):
    resolved = _resolve_task_output_path(path)
    if resolved.stat().st_size > FILE_SIZE_LIMIT:
        raise_error(413, "file_too_large", "ファイルが大きすぎます（上限 1MB）", limit="1MB")
    try:
        content = resolved.read_text(errors="replace")
    except Exception:
        logger.exception("failed to read task output: %s", resolved)
        raise HTTPException(status_code=500, detail="Internal error")
    return {"path": str(resolved), "content": content}


@router.get("/task-transcript")
def get_task_transcript(path: str = Query(...)):
    """<task-notification> の output-file が subagent jsonl symlink になった Claude Code 側
    仕様に追随する構造化 endpoint。 symlink 追跡後の実体が subagent jsonl なら parse して
    events 配列を返す (= /sessions/{sid}/subagents/{agent_id}/transcript と同じ描画情報)。

    /sessions 経路は現行 claude_sid 依存で、 session restart で drift すると 404 に倒れる。
    こちらは outputFile 引数を symlink 追跡だけで解決するので drift しない。 出力形状は
    /sessions transcript endpoint と揃える (= agentId / events + meta 任意)。 target が
    subagent jsonl でない (= Monitor / Bash 由来の raw output) 場合は 404 を返して frontend
    は /task-output raw 経路に fallback する。"""
    from backend.jsonl.events import subagent_line_to_events  # 局所 import: routes 起動時循環回避
    import json as _json
    resolved = _resolve_task_output_path(path)
    # symlink 追跡後の実体が subagent jsonl でなければ transcript 化不能。 /task-output 側の
    # 生読み経路に落として貰うため 404。
    if not _is_subagent_jsonl(resolved):
        raise HTTPException(status_code=404, detail="Not a subagent transcript")
    if resolved.stat().st_size > FILE_SIZE_LIMIT:
        raise_error(413, "file_too_large", "ファイルが大きすぎます（上限 1MB）", limit="1MB")
    events: list[dict] = []
    try:
        with resolved.open() as fh:
            for raw in fh:
                try:
                    line = _json.loads(raw)
                except _json.JSONDecodeError:
                    continue
                events.extend(subagent_line_to_events(line))
    except OSError:
        logger.exception("failed to read task transcript: %s", resolved)
        raise HTTPException(status_code=500, detail="Internal error")
    # agent_id は agent-<id>.jsonl の stem から抽出 (= SubagentsModal 側で focus 用に使う)
    agent_id = resolved.stem
    return {"agentId": agent_id, "path": str(resolved), "events": events}


@router.get("/files/tree")
def get_tree(path: str = Query(default="~")):
    resolved = _resolve_safe(path)
    if not resolved.exists():
        raise HTTPException(status_code=404, detail="Directory not found")
    if not resolved.is_dir():
        raise HTTPException(status_code=400, detail="Not a directory")
    entries = []
    try:
        # dotfile (= `.` で始まるエントリ) は非表示。 .git / .DS_Store / .env など普段
        # 触らないファイルが大量に並んで本来見たいものが埋もれるため。
        for entry in sorted(resolved.iterdir(), key=lambda e: (e.is_file(), e.name.lower())):
            if entry.name.startswith("."):
                continue
            entries.append({
                "name": entry.name,
                "path": str(entry),
                "is_dir": entry.is_dir(),
            })
    except PermissionError:
        raise HTTPException(status_code=403, detail="Permission denied")
    return {"path": str(resolved), "entries": entries}
