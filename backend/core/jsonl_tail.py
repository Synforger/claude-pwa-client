"""JSONL ファイル tail の低レベルプリミティブ。

SSE 配信 (`jsonl_routes._jsonl_sse`) と push 監視 (`monitor_all_sessions_loop`)
が共有する純粋関数群。 backend mem state には触らず、 path + offset → 行リスト
の関数だけを持つ。
"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path


def parse_jsonl_timestamp(ts: str | None) -> float | None:
    """JSONL 行の `timestamp` (= ISO 8601 "Z" 終端) を unix epoch に変換。"""
    if not ts or not isinstance(ts, str):
        return None
    try:
        return datetime.fromisoformat(ts.replace("Z", "+00:00")).timestamp()
    except (ValueError, TypeError):
        return None


def read_complete_lines_with_pos(path: Path, pos: int) -> tuple[list[tuple[str, int]], int]:
    """pos (= バイト位置) から読み、 改行で終わる完全な行を「その行を読み終えた byte 位置」
    とペアで返す。

    書き込み途中の不完全行 (= 末尾が \\n でない) は次回に持ち越すため、 pos は最後の
    完全行の直後までしか進めない。 per-line pos は SSE の id 行 (= client 側 offset の
    前進) に使う。 byte 単位で分割してから decode するので、 マルチバイト文字を跨いでも
    pos がずれない。 返り値 ([(行, 行末 byte 位置)], 新 pos)。
    """
    try:
        with open(path, "rb") as f:
            f.seek(pos)
            data = f.read()
    except OSError:
        return [], pos
    if not data:
        return [], pos
    last_nl = data.rfind(b"\n")
    if last_nl == -1:
        # 完全行がまだ無い (= 書き込み途中)
        return [], pos
    complete = data[: last_nl + 1]
    new_pos = pos + len(complete)
    out: list[tuple[str, int]] = []
    cursor = pos
    for raw in complete.split(b"\n")[:-1]:  # 末尾要素は空 (= 終端 \n の右側)
        cursor += len(raw) + 1  # +1 = 改行分
        if raw:
            out.append((raw.decode("utf-8", errors="replace"), cursor))
    return out, new_pos


def read_complete_lines(path: Path, pos: int) -> tuple[list[str], int]:
    """pos (= バイト位置) から読み、 改行で終わる完全な行だけ返す (= pos なし版 wrapper)。

    実装は read_complete_lines_with_pos に委譲 (= 分割ロジックの二重実装を作らない)。
    返り値 (完全行のリスト, 新 pos)。
    """
    pairs, new_pos = read_complete_lines_with_pos(path, pos)
    return [ln for ln, _ in pairs], new_pos


def read_tail_with_pos(path: Path, pos: int) -> tuple[list[tuple[str, int]], int, str]:
    """path を pos から tail する共通プリミティブ (= per-line pos 付き、 monitor が使う)。

    返り値 (lines_with_pos, new_pos, status):
      - "ok"        : 新規完全行あり (lines / new_pos が進む)
      - "nochange"  : 新着なし (new_pos == pos)
      - "truncated" : size < pos (= rotate / truncate。 new_pos = 現 size)
      - "error"     : stat 失敗 (= ファイル消失等)
    truncate 後にどこから読み直すかは呼び側の方針 (= SSE は先頭再生、 monitor は末尾再同期)。
    """
    try:
        size = path.stat().st_size
    except OSError:
        return [], pos, "error"
    if size < pos:
        return [], size, "truncated"
    if size <= pos:
        return [], pos, "nochange"
    lines_with_pos, new_pos = read_complete_lines_with_pos(path, pos)
    return lines_with_pos, new_pos, "ok"


def read_tail(path: Path, pos: int) -> tuple[list[str], int, str]:
    """read_tail_with_pos の pos なし版 wrapper (= 既存 consumer 互換)。"""
    lines_with_pos, new_pos, status = read_tail_with_pos(path, pos)
    return [ln for ln, _ in lines_with_pos], new_pos, status


def initial_offset(path: Path, max_lines: int) -> int:
    """初回 replay の開始バイト位置 (= 直近 max_lines 行ぶんに絞る、 backend-F-41)。

    末尾から固定 chunk ずつ遡って改行を数え、 「末尾から N 個目の改行の直後」 を返す。
    ファイル全体をメモリに読まないので大きい JSONL でも O(末尾) で済む。 改行が
    max_lines 個以下なら 0 (= 全件 replay)。 旧 jsonl/routes._initial_offset (=
    INITIAL_REPLAY_LINES = 500 固定値) と同じ境界 (= count <= N → 0、 count > N → N
    個目直後) を保つ。 routes 内に閉じていたものを tail.py に移送して unit test 厚く
    する + subagents.py 等の他 consumer からも再利用可能にする。
    """
    try:
        size = path.stat().st_size
    except OSError:
        return 0
    if size == 0:
        return 0
    chunk_size = 64 * 1024
    found = 0
    candidate = 0  # 末尾から N 個目の改行直後。 N+1 個目が見つかったら (= count > N) 返す
    pos = size
    try:
        with open(path, "rb") as f:
            while pos > 0:
                read_size = min(chunk_size, pos)
                pos -= read_size
                f.seek(pos)
                chunk = f.read(read_size)
                for i in range(len(chunk) - 1, -1, -1):
                    if chunk[i] != 0x0A:  # b"\n"
                        continue
                    found += 1
                    if found == max_lines:
                        candidate = pos + i + 1
                    elif found > max_lines:
                        return candidate
    except OSError:
        return 0
    return 0
