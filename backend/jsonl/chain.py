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


@dataclass(frozen=True)
class Window:
    """つないだ記録から切り出した窓。 lines は [(行, 行末の通しの位置)]、 end は読み終えた通しの位置。

    reached は、 呼び手が渡した since の直後の行から欠けずに返したか (= since を渡さなかった時は測れないので False)。
    """
    lines: list[tuple[str, int]]
    end: int
    reached: bool

    def after(self, position: int | None) -> list[tuple[str, int]]:
        """窓の行のうち position (= 画面が描き終えた位置) より後ろの行。 position が無い / 今の終わりより先を指す時は窓の全部。"""
        if position is None or not 0 <= position <= self.end:
            return self.lines
        return [(raw, pos) for raw, pos in self.lines if pos > position]


def read_window(
    segs: list[Segment], since: int | None, recent_lines: int, limit_lines: int,
) -> Window:
    """つないだ記録の窓を返す。 窓の頭は「直近 recent_lines 行の頭」と since の早い方で、 直近 limit_lines 行より前にはしない。

    since は画面が描き終えた通しの位置。 画面を閉じている間に書かれた行が recent_lines を超えても、 since まで
    遡って返す (= 画面の中に穴が空かない)。 limit_lines を超える時は直近 limit_lines 行までで、 reached は False。
    since が今の終わりより先を指す時 (= 画面の位置が先行した) は、 抜けが無いので直近 recent_lines 行で reached は True。
    読むのは窓の分だけ (= 頭の位置は末尾から改行を数えて決め、 窓の外の行は読まない)。
    """
    if not segs:
        return Window([], 0, since is not None)
    picked: list[tuple[str, int]] = []
    end = segs[-1].base
    remaining_limit = limit_lines
    remaining_recent = recent_lines
    head: int | None = None  # 打ち切った時の窓の頭の通しの位置 (= 古い記録まで全部読んだ時は None)
    for index, seg in enumerate(reversed(segs)):
        # initial_offset(path, n) は n 行より多い file では n - 1 行の所を返す。 1 行多く頼んで n 行にする。
        recent_offset = initial_offset(seg.path, remaining_recent + 1)
        since_offset = None if since is None else max(0, since - seg.base)
        if since_offset is None or since_offset >= recent_offset:
            local_head = recent_offset  # since が直近の窓の中 (= 普段の再接続)。 上限の位置は測らずに済む
        else:
            local_head = max(initial_offset(seg.path, remaining_limit + 1), since_offset)
        pairs, new_pos = read_complete_lines_with_pos(seg.path, local_head)
        if index == 0:
            end = seg.base + new_pos
        needed = remaining_recent
        if since is not None:
            needed = max(needed, sum(1 for _raw, pos in pairs if seg.base + pos > since))
        cut = max(0, len(pairs) - min(needed, remaining_limit))
        if cut:
            local_head = pairs[cut - 1][1]  # 切り落とした最後の行の行末 = 残す最初の行の頭
        kept = pairs[cut:]
        picked = [(raw, seg.base + pos) for raw, pos in kept] + picked
        remaining_limit -= len(kept)
        remaining_recent = max(0, remaining_recent - len(kept))
        if local_head > 0 or remaining_limit <= 0:
            head = seg.base + local_head
            break
    reached = since is not None and (head is None or head <= since)
    return Window(picked, end, reached)


def read(segs: list[Segment], start: int | None, max_lines: int) -> tuple[list[tuple[str, int]], int]:
    """つないだ記録を、 start (= 画面が読み終えた通しの位置) より後ろの行だけ、 直近 max_lines 行まで読む。

    返り値 ([(行, 行末の通しの位置)], 読み終えた通しの位置)。 久しぶりに開いたタブの全区間を流し直すと、
    画面の表示上限を大きく超えて CPU を焼くだけなので、 窓は max_lines 行までにする。 start が無い /
    どの記録も指していない時は、 直近 max_lines 行。
    """
    window = read_window(segs, start, max_lines, max_lines)
    return window.after(start), window.end
