"""claude が打鍵を受け取れる状態かを PWA session ごとに持つ旗。

送信経路 (= `/pty/{sid}/send`) が見ていたのは tmux session の存在だけで、 pane の中身が
zsh でも起動途中の claude でも真になっていた。 セッション終了 (= restart) 直後は
「tmux は在るが claude はまだ起動していない」 窓が数秒あり、 そこへ本文 + Enter を打つと
claude はまだ端末を読んでいないので入力が端末の待ち行列に溜まり、 TUI が立ち上がった
瞬間に 1 度に読まれる。 送信側が本文と Enter を 0.3s 空けても、 読み手が読んでいなければ
その間隔は消える。 結果 Enter が確定でなく本文の改行として入り、 本文だけが入力欄に残る。

実測 (= 2026-09-08、 restart 44 回):

    送信が SessionStart hook より前  14 件 → 14 件とも未達 (= 5.3s 〜 2h25m 遅れ)
    送信が SessionStart hook より後  30 件 → 25 件が 0.1s 以内に着弾

旗の意味:
    未登録   = 判定材料が無い (= 従来どおり素通しで打つ)
    starting = claude 起動中、 打鍵は待たせる
    ready    = claude 本体が SessionStart hook で起動を通知した
"""
from __future__ import annotations

import asyncio
import logging

logger = logging.getLogger(__name__)

# 旗が立つのを待つ上限。 実測 (= 同 44 回) の spawn → SessionStart は中央値 2.8s /
# 最大 16.0s。 待ち切れずに打つと本文が入力欄に取り残されるので、 実測最大に余裕を
# 足した値にする。 超えた時は打鍵せず失敗を返し、 本文を入力欄へ戻す経路に載せる。
INPUT_READY_TIMEOUT_SEC: float = 20.0

_events: dict[str, asyncio.Event] = {}


def _slot(session_id: str) -> asyncio.Event:
    ev = _events.get(session_id)
    if ev is None:
        ev = asyncio.Event()
        _events[session_id] = ev
    return ev


def mark_starting(session_id: str) -> None:
    """claude をこれから起動する (= 打鍵を待たせる)。 spawn が launch_alias を投入する
    経路だけが呼ぶ。 alias を投入しない再 attach は既に claude が走っているので対象外。"""
    _slot(session_id).clear()


def mark_ready(session_id: str) -> None:
    """claude が起動を通知した (= 打鍵してよい)。 SessionStart hook から呼ぶ。"""
    _slot(session_id).set()


def forget(session_id: str) -> None:
    """session ごと消える時に旗も落とす (= delete 経路)。"""
    _events.pop(session_id, None)


def is_ready(session_id: str) -> bool:
    """待たずに今の状態だけ見る (= 未登録は判定材料が無いので True)。"""
    ev = _events.get(session_id)
    return True if ev is None else ev.is_set()


async def wait_ready(session_id: str, timeout: float | None = None) -> bool:
    """claude が打鍵を受け取れるまで待つ。 待てたら True、 上限超過で False。

    上限を超えた時は旗を立てて返す (= 検出経路が効いていないのに次の送信まで毎回
    待たせない)。 呼び手は False を受けたら打鍵せず失敗を返し、 本文を入力欄へ戻す。
    """
    ev = _events.get(session_id)
    if ev is None or ev.is_set():
        return True
    # 既定値は import 時でなく呼び出し時に読む (= 上限を差し替えて試験できる形)
    timeout = INPUT_READY_TIMEOUT_SEC if timeout is None else timeout
    try:
        await asyncio.wait_for(ev.wait(), timeout=timeout)
        return True
    except asyncio.TimeoutError:
        logger.warning(
            "input_ready: claude did not report startup within %.1fs session=%s; "
            "refusing to type into a pane that is not listening yet",
            timeout, session_id,
        )
        ev.set()
        return False
