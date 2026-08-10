"""並列エージェントの会議を読む / 書く。

会議は markdown 3 枚で表される。 実体は agent state tree の側にあり、 backend は
`CPC_MEETINGS_ROOT` で受け取った root の下だけを見る:

```
<root>/**/meetings/<topic>/          進行中
<root>/**/meetings/_archive/<topic>/ 終了済み
    contract.md   参加者が従う取り決め (= 司令塔だけが書く)
    board.md      発言の追記ログ
    status.md     参加者ごとの現在地 (= markdown table)
```

root に既定値を置かないのは仕様。 置き場は運用者の私的な path であって、 公開
repo が知っていて良いものではない。 未設定なら全 endpoint が 404 を返し、 「機能が
無い」 と 「会議が 0 件」 を取り違えないようにする。

会議の指定は id (= tier と topic を base64url で畳んだ不透明な文字列) で行う。 path
に階層名を載せないので、 `..` を含む要求が構造的に作れない。 復号後も root 配下で
あることを実体 path で再検査する (= symlink 経由の脱出を許さない)。
"""
from __future__ import annotations

import base64
import binascii
import json
import logging
import re
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from backend.paths import MEETINGS_ROOT

logger = logging.getLogger(__name__)
router = APIRouter()

# 掲示板に書ける 4 種。 行頭のこの語だけが発言の種類を決める。 これ以外で始まる行は
# 直前の発言の本文として扱う (= 捨てない)。
KIND_BY_PREFIX = {
    "報告": "report",
    "異議": "objection",
    "裁定": "ruling",
    "指示": "directive",
}
PREFIX_BY_KIND = {v: k for k, v in KIND_BY_PREFIX.items()}

# `## 04:12 @swift` / `## 2026-08-10 04:12 @司令塔` のどちらも受ける。
_HEADER = re.compile(r"^##\s+(?P<at>[^@]*?)\s*@(?P<who>\S+)\s*$")
_KIND_LINE = re.compile(r"^(?P<prefix>報告|異議|裁定|指示)\s*[:：]\s*(?P<body>.*)$")

# 雛形と隠しフォルダは会議ではない。
_SKIP_DIRS = {"_template", "_archive"}


def _require_root() -> Path:
    if MEETINGS_ROOT is None or not MEETINGS_ROOT.is_dir():
        raise HTTPException(status_code=404, detail="meetings root is not configured")
    return MEETINGS_ROOT


def _encode_id(tier: str, topic: str, state: str) -> str:
    raw = json.dumps([tier, topic, state], ensure_ascii=False).encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _decode_id(meeting_id: str) -> tuple[str, str, str]:
    pad = "=" * (-len(meeting_id) % 4)
    try:
        raw = base64.urlsafe_b64decode(meeting_id + pad)
        tier, topic, state = json.loads(raw.decode("utf-8"))
    except (binascii.Error, UnicodeDecodeError, json.JSONDecodeError, ValueError, TypeError):
        raise HTTPException(status_code=404, detail="unknown meeting")
    if state not in ("active", "archived"):
        raise HTTPException(status_code=404, detail="unknown meeting")
    return tier, topic, state


def _meeting_dir(tier: str, topic: str, state: str) -> Path:
    """id が指す folder を返す。 root の外を指していたら 404。

    id は不透明だが、 手で作れないわけではない。 復号した値をそのまま繋ぐと
    `..` で外へ出られるので、 実体 path に解決してから root 配下か確かめる
    (= symlink を辿った先が外だった場合もここで落ちる)。
    """
    root = _require_root()
    base = root / tier / "meetings"
    target = (base / "_archive" / topic) if state == "archived" else (base / topic)
    try:
        resolved = target.resolve()
    except OSError:
        raise HTTPException(status_code=404, detail="unknown meeting")
    if not resolved.is_dir() or root not in resolved.parents:
        raise HTTPException(status_code=404, detail="unknown meeting")
    return resolved


def _read(path: Path) -> str | None:
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None


def parse_board(text: str) -> list[dict]:
    """board.md を発言の並びへ。 追記順のまま返す (= 並べ替えない)。

    見出し行が発言の境目。 見出しより前の文章 (= 使い方の注記) は発言ではないので
    落とす。 本文のうち 4 種のどれかで始まる行はその種類の発言になり、 それ以外の行は
    直前の発言へ続けて足す (= 複数行の報告を千切らない)。
    """
    posts: list[dict] = []
    who: str | None = None
    at = ""
    current: dict | None = None

    for line in text.splitlines():
        header = _HEADER.match(line)
        if header:
            who = header.group("who")
            at = header.group("at").strip()
            current = None
            continue
        if who is None:
            continue
        kind_line = _KIND_LINE.match(line.strip())
        if kind_line:
            current = {
                "at": at,
                "who": who,
                "kind": KIND_BY_PREFIX[kind_line.group("prefix")],
                "body": kind_line.group("body").strip(),
            }
            posts.append(current)
            continue
        if not line.strip():
            continue
        if current is not None:
            current["body"] = f"{current['body']}\n{line.strip()}".strip()
        else:
            current = {"at": at, "who": who, "kind": "other", "body": line.strip()}
            posts.append(current)
    return posts


def parse_status(text: str) -> list[dict]:
    """status.md の table を参加者の並びへ。

    列は `担当 | 契約の版 | 状態 | 今どこ | 最終確認` を想定するが、 会議ごとに
    増減しうるので、 位置ではなく**見出しの語**で拾う。 見出しが読めない table は
    参加者なしとして扱う (= 誤った列を状態として出すより空の方が安全)。
    """
    rows = [ln.strip() for ln in text.splitlines() if ln.strip().startswith("|")]
    if len(rows) < 2:
        return []

    def cells(row: str) -> list[str]:
        return [c.strip() for c in row.strip("|").split("|")]

    header = cells(rows[0])

    def col(*names: str) -> int | None:
        for i, h in enumerate(header):
            if any(n in h for n in names):
                return i
        return None

    i_name = col("担当", "name")
    if i_name is None:
        return []
    i_ver, i_state = col("版", "version"), col("状態", "state")
    i_note, i_read = col("今どこ", "note"), col("確認", "read")

    out: list[dict] = []
    for row in rows[1:]:
        c = cells(row)
        if not c or set("".join(c)) <= set("-: "):  # 区切り行
            continue
        if i_name >= len(c) or not c[i_name]:
            continue

        def at(idx: int | None) -> str | None:
            if idx is None or idx >= len(c):
                return None
            return c[idx] or None

        out.append(
            {
                "name": c[i_name].lstrip("@"),
                "version": at(i_ver),
                "state": at(i_state) or "unknown",
                "note": at(i_note),
                "read_at": at(i_read),
            }
        )
    return out


def _iter_meetings(root: Path):
    """root 配下の全 meetings/ を舐めて (tier, topic, state, dir) を返す。"""
    for meetings_dir in sorted(root.glob("**/meetings")):
        if not meetings_dir.is_dir():
            continue
        tier = meetings_dir.parent.relative_to(root).as_posix() or "."
        for child in sorted(meetings_dir.iterdir()):
            if not child.is_dir() or child.name in _SKIP_DIRS or child.name.startswith("."):
                continue
            yield tier, child.name, "active", child
        archive = meetings_dir / "_archive"
        if archive.is_dir():
            for child in sorted(archive.iterdir()):
                if not child.is_dir() or child.name.startswith("."):
                    continue
                yield tier, child.name, "archived", child


def _updated_at(meeting_dir: Path) -> str | None:
    board = meeting_dir / "board.md"
    try:
        ts = board.stat().st_mtime
    except OSError:
        return None
    return datetime.fromtimestamp(ts, tz=timezone.utc).isoformat()


@router.get("/meetings")
async def list_meetings():
    root = _require_root()
    items = [
        {
            "id": _encode_id(tier, topic, state),
            "tier": tier,
            "topic": topic,
            "state": state,
            "updated_at": _updated_at(path),
        }
        for tier, topic, state, path in _iter_meetings(root)
    ]
    return JSONResponse(items)


@router.get("/meetings/{meeting_id}")
async def get_meeting(meeting_id: str):
    tier, topic, state = _decode_id(meeting_id)
    path = _meeting_dir(tier, topic, state)
    board = _read(path / "board.md") or ""
    status = _read(path / "status.md") or ""
    return JSONResponse(
        {
            "id": meeting_id,
            "tier": tier,
            "topic": topic,
            "state": state,
            "contract": _read(path / "contract.md"),
            "posts": parse_board(board),
            "participants": parse_status(status),
        }
    )


class PostBody(BaseModel):
    who: str
    kind: str
    body: str


@router.post("/meetings/{meeting_id}/posts")
async def append_post(meeting_id: str, payload: PostBody):
    tier, topic, state = _decode_id(meeting_id)
    if state == "archived":
        raise HTTPException(status_code=409, detail="meeting is closed")
    if payload.kind not in PREFIX_BY_KIND:
        raise HTTPException(status_code=422, detail="kind must be one of the four acts")
    who = payload.who.strip().lstrip("@")
    body = payload.body.strip()
    if not who or not body:
        raise HTTPException(status_code=422, detail="who and body are required")

    path = _meeting_dir(tier, topic, state)
    board = path / "board.md"
    stamp = datetime.now().strftime("%H:%M")
    block = f"\n## {stamp} @{who}\n{PREFIX_BY_KIND[payload.kind]}: {body}\n"
    try:
        # 追記のみ。 既存の行を読み書きする経路をこの module は持たない。
        with board.open("a", encoding="utf-8") as fh:
            fh.write(block)
    except OSError:
        logger.exception("failed to append to board")
        raise HTTPException(status_code=500, detail="failed to append")
    return JSONResponse({"ok": True})
