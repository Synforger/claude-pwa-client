"""お気に入り (= ⭐) の一覧。

真値は `USER_DIR/favorites.txt` の 1 本で、 1 行に 1 path (= `~/...` か絶対 path)。 画面はこの口から
読み書きし、 エージェントは file に 1 行足すだけで登録できる。 どの端末で開いても同じ一覧になり、
ブラウザが保存領域を消しても残る。

file に持つのは path だけ。 フォルダかどうかと表示名は、 読むたびに実物から導く (= 登録した後で
file がフォルダに変わっても、 名前を付け替えても、 一覧が古い値を持ち続けない)。

path として読めない行 (= 空行、 メモ書き) は一覧に出さず、 file からも消さない: 足す時は末尾に 1 行
足すだけ、 外す時はその path の行だけを抜く。
"""
import os
import threading
from pathlib import Path

from fastapi import APIRouter, Body, HTTPException, Query

import backend.paths as paths
from backend.config import HOME
from backend.state import atomic_write_text

router = APIRouter()

# 読んで書き戻す間に別の要求が割り込むと、 片方の 1 行が消える
_lock = threading.Lock()


def _to_path(line: str) -> str | None:
    """1 行を絶対 path に直す。 path として読めない行は None。"""
    text = line.strip()
    if not text:
        return None
    expanded = os.path.expanduser(text)
    if not os.path.isabs(expanded):
        return None
    return os.path.normpath(expanded)


def _to_line(path: str) -> str:
    """file に書く形 (= HOME の下は `~/...`。 人が読みやすく、 HOME の違う機械へ写しても通じる)。"""
    home = str(HOME)
    if path == home:
        return "~"
    if path.startswith(home + os.sep):
        return "~" + path[len(home):]
    return path


def _read_lines() -> list[str]:
    try:
        return paths.FAVORITES_PATH.read_text(encoding="utf-8", errors="replace").splitlines()
    except FileNotFoundError:
        return []


def _write_lines(lines: list[str]) -> None:
    paths.FAVORITES_PATH.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_text(paths.FAVORITES_PATH, "".join(f"{line}\n" for line in lines))


def _is_dir(path: str) -> bool:
    # 実物を見に行くのは HOME の下だけ (= `/file` が見せる範囲と同じ)
    try:
        Path(path).relative_to(HOME)
    except ValueError:
        return False
    return os.path.isdir(path)


def _entries(lines: list[str]) -> list[dict]:
    seen: set[str] = set()
    out: list[dict] = []
    for line in lines:
        path = _to_path(line)
        if path is None or path in seen:
            continue
        seen.add(path)
        out.append({"path": path, "name": os.path.basename(path) or path, "is_dir": _is_dir(path)})
    return out


def _required_path(raw: str) -> str:
    if "\n" in raw or "\r" in raw:
        raise HTTPException(status_code=400, detail="path must be a single line")
    path = _to_path(raw)
    if path is None:
        raise HTTPException(status_code=400, detail="path must be absolute or start with ~")
    return path


@router.get("/favorites")
def list_favorites():
    return {"favorites": _entries(_read_lines())}


@router.post("/favorites")
def add_favorite(path: str = Body(..., embed=True)):
    target = _required_path(path)
    with _lock:
        lines = _read_lines()
        if all(_to_path(line) != target for line in lines):
            lines.append(_to_line(target))
            _write_lines(lines)
        return {"favorites": _entries(lines)}


@router.delete("/favorites")
def remove_favorite(path: str = Query(...)):
    target = _required_path(path)
    with _lock:
        lines = _read_lines()
        kept = [line for line in lines if _to_path(line) != target]
        if len(kept) != len(lines):
            _write_lines(kept)
        return {"favorites": _entries(kept)}
