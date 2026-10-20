"""ホームディレクトリ配下のファイル閲覧・編集 / ディレクトリツリー取得。

セキュリティ: tailnet 経由で誰でも `/file` を叩けるので、 秘密ファイル (= SSH 鍵 / クラウド
認証情報 / token を平文で持つ設定 / シェル初期化ファイル) は読み書き両方禁止。 HOME 配下 deny list ベース。
"""
import logging
import os
import re
from pathlib import Path
from urllib.parse import quote

from fastapi import APIRouter, Body, FastAPI, HTTPException, Query, Request
from fastapi.responses import FileResponse, RedirectResponse

from backend.config import FILE_SIZE_LIMIT, HOME, page_origin
from backend.errors import raise_error

logger = logging.getLogger(__name__)
router = APIRouter()


# 読み書きを完全に禁止するパス / 拡張子 / ファイル名のパターン。 HOME 配下に存在しても
# `/file` 経由では到達させない。 リモートシェル奪取 / 認証情報漏洩経路を物理的に塞ぐ。
#
# 並びは「鍵と認証情報の置き場 → token を平文で持つ設定 → シェルの初期化と履歴」。 token を持つ設定は
# ホームの直下に限らない (= `.env` / `.envrc` は repo ごと、 `secrets/` はアプリごとに在る) ので、
# 場所ではなく名前で拒む。 `.env.example` のような雛形は中身が見本なので通す。
_DENY_RE = re.compile(
    r"(?:^|/)(?:"
    r"\.ssh|\.aws|\.gnupg|\.kube|\.docker|\.azure|\.config/gh|\.config/gcloud|Library/Keychains|"
    r"\.netrc|\.npmrc|\.pypirc|\.git-credentials|\.pgpass|"
    r"\.envrc|\.credentials\.json|\.claude\.json|secrets|"
    r"\.zshrc|\.zshenv|\.zprofile|\.bashrc|\.bash_profile|\.profile|"
    r"\.zsh_history|\.bash_history"
    r")(?:$|/)"
    r"|(?:^|/)\.env(?:\.(?!(?:example|sample|template)$)[^/]*)?$"
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


# 画像の生バイト (= プレビューの <img> 用)。 `/file` は中身を文字として読んで JSON で返すので、
# 画像はここで返す。 対象は添付と同じ 4 形式だけで、 SVG は外す (= スクリプトを持てるので、 同じ
# origin で直に開かれると script が走る)。 HOME 配下 / deny list の制限は `/file` と同じ。
_IMAGE_MEDIA_TYPES = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif": "image/gif",
    ".webp": "image/webp",
}
# スマホのスクリーンショット (= 数 MB) は通し、 巨大な素材で backend が詰まらない上限。
IMAGE_SIZE_LIMIT = 10 * 1024 * 1024


@router.get("/file/raw")
def get_file_raw(path: str = Query(...)):
    resolved = _resolve_safe(path)
    media_type = _IMAGE_MEDIA_TYPES.get(resolved.suffix.lower())
    if media_type is None:
        raise HTTPException(status_code=415, detail="Unsupported media type")
    if not resolved.exists():
        raise HTTPException(status_code=404, detail="File not found")
    if not resolved.is_file():
        raise HTTPException(status_code=400, detail="Not a file")
    if resolved.stat().st_size > IMAGE_SIZE_LIMIT:
        raise_error(413, "file_too_large", "画像が大きすぎます（上限 10MB）", limit="10MB")
    return FileResponse(
        resolved,
        media_type=media_type,
        headers={"Cache-Control": "no-cache", "X-Content-Type-Options": "nosniff"},
    )


# HTML を、 隣の file (= 画像・スクリプト・CSS・フォント) ごとブラウザで開く口。 `/file/view/<HOME 配下の
# 絶対 path>` で配るので、 HTML の中の相対 path (= `cam/a.jpg`) は同じ口でそのまま読める。 スクリプトが動く形で
# 開くので、 どの応答にも sandbox の CSP を付ける: ページの origin は backend と別 (= null) になり、 fetch /
# WebSocket は connect-src で止まり、 読める画像・スクリプト・CSS はこの backend の物だけ。 ページは backend の
# 状態を変える口を叩けず (= 届くのは画像の形の GET だけで、 GET の口は読むだけ)、 外へも何も送れない。
# HOME 配下 / deny list の制限は `/file` と同じ。
_VIEW_MEDIA_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".htm": "text/html; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
    ".mjs": "text/javascript; charset=utf-8",
    ".json": "application/json",
    ".csv": "text/csv; charset=utf-8",
    ".txt": "text/plain; charset=utf-8",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif": "image/gif",
    ".webp": "image/webp",
    ".svg": "image/svg+xml",
    ".ico": "image/x-icon",
    ".woff": "font/woff",
    ".woff2": "font/woff2",
    ".ttf": "font/ttf",
    ".otf": "font/otf",
    ".mp4": "video/mp4",
    ".webm": "video/webm",
    ".mp3": "audio/mpeg",
    ".m4a": "audio/mp4",
    ".wav": "audio/wav",
}
# 図解の動画や大きな画像は通し、 巨大な素材で backend が詰まらない上限 (= 1 file ごと)。
VIEW_SIZE_LIMIT = 50 * 1024 * 1024
# ページが読める物と送れる先 (= /file/view とページの origin で共通。 違うのは sandbox と frame-ancestors だけ)。
_PAGE_POLICY = (
    "default-src 'none'; "
    "script-src 'self' 'unsafe-inline' 'unsafe-eval' blob:; style-src 'self' 'unsafe-inline'; "
    "img-src 'self' data: blob:; media-src 'self' data: blob:; font-src 'self' data:; "
    "connect-src 'none'; form-action 'none'; base-uri 'none'"
)
# frame-ancestors は同じ host だけ (= iPhone のホーム画面の PWA は、 HTML をプレビューの枠の iframe に嵌めて開く)。
VIEW_CSP = f"sandbox allow-scripts; {_PAGE_POLICY}; frame-ancestors 'self'"
_VIEW_HEADERS = {
    "Cache-Control": "no-cache",
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",
}


# ページの origin の待ち受けが開いているか (= main の _PageServer が書く。 開けなかった間は今どおり /file/view で開く)
page_listening = False


def _same_host(request: Request, port: str | int) -> str:
    """今の要求と同じ scheme と host の、 別の port (= IPv6 の住所は括弧で包む)。"""
    host = request.url.hostname or ""
    return f"{request.url.scheme}://{f'[{host}]' if ':' in host else host}:{port}"


def _page_target(resolved: Path, request: Request) -> str | None:
    """page_origin の folder の中の file なら、 それを配る別の port の URL (= 外か、 待ち受けが開いていなければ None)。

    host と scheme は今の要求の物を使う (= Tailscale の serve 越しなら https、 手元なら http)。 別の port も同じ
    host の同じ番号で届く前提 (= Tailscale では同じ番号の port を serve で出す)。
    """
    origin = page_origin()
    if origin is None or not page_listening:
        return None
    folder, port = origin
    try:
        rel = resolved.relative_to(folder)
    except ValueError:
        return None
    return f"{_same_host(request, port)}/{quote(rel.as_posix())}"


@router.get("/file/open")
def open_file_in_browser(request: Request, path: str = Query(...)):
    """チャットの path (= `~/…` も可) の HTML を、 page_origin の folder の中なら別の port へ、 それ以外は
    `/file/view/<絶対 path>` へ回す。"""
    resolved = _resolve_safe(path)
    if resolved.suffix.lower() not in (".html", ".htm"):
        raise HTTPException(status_code=415, detail="Unsupported media type")
    if not resolved.is_file():
        raise HTTPException(status_code=404, detail="File not found")
    target = _page_target(resolved, request)
    if target is not None:
        return RedirectResponse(url=target, status_code=307)
    # 相対の行き先 (= backend が path の前置きの下に置かれても、 同じ前置きの下の view へ回る)。
    return RedirectResponse(url="view/" + quote(str(resolved).lstrip("/")), status_code=307)


def _view_response(resolved: Path, csp: str) -> FileResponse:
    """/file/view とページの origin が配る 1 file (= 形・在るか・大きさを確かめ、 CSP を付けて返す)。"""
    media_type = _VIEW_MEDIA_TYPES.get(resolved.suffix.lower())
    if media_type is None:
        raise HTTPException(status_code=415, detail="Unsupported media type")
    if not resolved.is_file():
        raise HTTPException(status_code=404, detail="File not found")
    if resolved.stat().st_size > VIEW_SIZE_LIMIT:
        raise_error(413, "file_too_large", "ファイルが大きすぎます（上限 50MB）", limit="50MB")
    return FileResponse(
        resolved, media_type=media_type, headers={"Content-Security-Policy": csp, **_VIEW_HEADERS},
    )


@router.get("/file/view/{path:path}")
def get_file_view(path: str):
    return _view_response(_resolve_safe("/" + path), VIEW_CSP)


# ページの origin: page_origin の folder の file を、 sandbox を外した普通のページとして配る口。 backend とは別の
# 待ち受け (= 別の port。 立てるのは main の lifespan) なので、 ページの origin は backend と別になり、 その origin の
# localStorage は開き直しても残る (= /file/view の sandbox の origin は毎回 null で、 何も残らない)。 sandbox の他は
# /file/view と同じで、 fetch / WebSocket は connect-src で止まり (= backend の口にも外にも届かない)、 読める画像・
# スクリプト・CSS はこの port の物だけ。 folder の中の全部のページが 1 つの origin を共有する。 frame-ancestors は
# 同じ host の全部の port (= ホーム画面の PWA は、 backend の origin のプレビューの枠に嵌めて開く)。
page_app = FastAPI(openapi_url=None, docs_url=None, redoc_url=None)


@page_app.get("/{path:path}")
def get_page(request: Request, path: str):
    origin = page_origin()
    if origin is None:
        raise HTTPException(status_code=404, detail="File not found")
    folder = origin[0]
    resolved = (folder / path).resolve()
    try:
        resolved.relative_to(folder)
    except ValueError:
        raise HTTPException(status_code=403, detail="Access denied")
    csp = f"{_PAGE_POLICY}; frame-ancestors {_same_host(request, '*')}"
    return _view_response(_resolve_safe(str(resolved)), csp)


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
    # HOME 直下の Claude Code の config dir (= `.claude` / 別 account の `.claude-work`)
    # の projects dir の下でよい。
    try:
        rel_home = resolved.relative_to(HOME.resolve())
    except (OSError, ValueError):
        return False
    if len(rel_home.parts) < 3 or not rel_home.parts[0].startswith(".claude") or rel_home.parts[1] != "projects":
        return False
    rel = Path(*rel_home.parts[2:])
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
