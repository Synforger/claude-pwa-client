"""タブの状態の語 (= `tabs list` の状態の欄) を、 そのタブについて分かっている事から決める。 呼ぶのは `tabs list`。

この機械のタブと別の機械のタブは同じ語を同じ順で決める: claude が動いていればその状態、 でなければ
眠り → 未起動 → 起こせない。
"""
from __future__ import annotations

from backend.cli.claude_sessions import UNKNOWN_STATUS

ASLEEP = "眠り"
NOT_STARTED = "未起動"
CANNOT_WAKE = "起こせない"


def state_word(status: str | None, *, asleep: bool, reachable: bool) -> str:
    """`status` は動いている claude の状態の語 (= 居なければ None)、 `asleep` は眠らせてあるか、 `reachable` は連絡で
    claude を起動できるか。"""
    if status is not None:
        return status
    if asleep:
        return ASLEEP
    return NOT_STARTED if reachable else CANNOT_WAKE


def peer_tab_state(tab: dict) -> str:
    """別の機械の backend が返したタブ 1 つの状態の語。 `running` は連絡が届くか、 `status` は動いている claude の状態、
    `asleep` は眠っているか。 状態の欄を持たない古い backend の行は、 届くなら `?`、 届かないなら起こせない。"""
    if "status" not in tab:
        return UNKNOWN_STATUS if tab.get("running") else CANNOT_WAKE
    return state_word(tab["status"], asleep=bool(tab.get("asleep")), reachable=bool(tab.get("running")))
