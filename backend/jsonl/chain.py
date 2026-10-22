"""タブの記録の並び (= 前の会話から今の会話まで) と、 それを 1 本につないだ通しの位置。

1 つのタブ (= pwa_sid) の中で、 claude の会話は入れ替わる (= 自動の入れ替え / セッション終了 / `/clear`)。
記録 (= jsonl) は会話ごとに別の file になるが、 画面から見ればタブの会話は 1 本の続きで、 入れ替えの後も
それまでの会話はタブに残る (= docs/reference/rollover.md)。

画面へ渡す位置 (= 流し直しと live の frame の pos、 履歴 GET の pos) は、 file ごとの byte 位置ではなく、
タブの記録を古い順につないだ通しの byte 位置にする。 各記録の起点は控え (= backend/jsonl/history.py) が
持ち、 一度決めたら動かさない。 これで:

- 画面を閉じている間に会話が入れ替わっても、 前の会話の残り (= 締めの作業と、 入れ替えの発話) を流し直せる
- 画面の offset が前の会話の位置か今の会話の位置かを取り違えない (= file ごとの位置だった頃は、 今の会話の
  記録が前の会話の offset より育つと、 今の会話の頭を飛ばしていた)
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from backend.jsonl.jsonl_tail import initial_offset, read_complete_lines_with_pos
from backend.jsonl import history


@dataclass(frozen=True)
class Segment:
    """タブの記録の 1 本 (= 1 つの会話の jsonl) と、 通しの位置での起点。"""
    path: Path
    base: int


def segments(sid: str, current: Path | None) -> list[Segment]:
    """タブの記録を古い順に返す。 最後が今の会話 (= current)。 消えた記録は除く。

    current は呼び手が `_latest_jsonl(sid)` で引いた今の会話の記録 (= 引けなければ None で、 終わった
    会話だけを返す)。 今の会話が控えに載っている (= 終わった直後で、 次の会話がまだ起動していない) 時は、
    控えの起点をそのまま使う。
    """
    out: list[Segment] = []
    current_base: int | None = None
    for path, base in history.ended(sid):
        if path is None:
            continue
        if current is not None and path == current:
            current_base = base
            continue
        if path.is_file():
            out.append(Segment(path, base))
    if current is not None:
        out.append(Segment(current, history.next_base(sid) if current_base is None else current_base))
    return out


def base_of(sid: str, current: Path) -> int:
    """今の会話の記録の起点 (= live の行の file 内の位置に足すと、 通しの位置になる)。"""
    return segments(sid, current)[-1].base


def _size(path: Path) -> int:
    try:
        return path.stat().st_size
    except OSError:
        return 0


def read(segs: list[Segment], start: int | None, max_lines: int) -> tuple[list[tuple[str, int]], int]:
    """つないだ記録を、 start (= 画面が読み終えた通しの位置) から読む。

    返り値 ([(行, 行末の通しの位置)], 読み終えた通しの位置)。 読むのは直近 max_lines 行まで (= 久しぶりに
    開いたタブの全区間を流し直すと、 画面の表示上限を大きく超えて CPU を焼くだけ。 それより前は画面の
    localStorage の cache が持っている)。 start が無い / どの記録も指していない時は、 直近 max_lines 行。
    """
    if not segs:
        return [], 0
    cur = segs[-1]
    end = cur.base + _size(cur.path)
    if start is not None and cur.base <= start <= end:
        # 今の会話の中を指している (= つなぎ直しの普段の形)。 前の会話は読まない。
        local = max(start - cur.base, initial_offset(cur.path, max_lines))
        pairs, new_pos = read_complete_lines_with_pos(cur.path, local)
        return [(raw, cur.base + pos) for raw, pos in pairs], cur.base + new_pos
    picked: list[tuple[str, int]] = []
    remaining = max_lines
    for seg in reversed(segs):
        # initial_offset(path, n) は末尾の改行も 1 つと数えるので、 n 行より多い file では n - 1 行の所を
        # 返す。 1 行多く頼んで、 読んだ中から末尾の remaining 行を取る (= 記録をまたいで行数を揃える)。
        offset = initial_offset(seg.path, remaining + 1)
        pairs, new_pos = read_complete_lines_with_pos(seg.path, offset)
        if seg is cur:
            end = cur.base + new_pos
        taken = pairs[-remaining:]
        picked = [(raw, seg.base + pos) for raw, pos in taken] + picked
        if offset > 0 or len(pairs) > remaining:
            break  # この記録だけで足りた (= それより古い記録は読まない)
        remaining -= len(taken)
        if remaining <= 0:
            break
    if start is not None and 0 <= start <= end:
        picked = [(raw, pos) for raw, pos in picked if pos > start]
    return picked, end
