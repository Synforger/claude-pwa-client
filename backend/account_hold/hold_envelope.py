"""The messages the account hold sends a tab: the request to come to a break before it is stopped, and the request to
carry on once the operator continues it. The first line is the one the client's own notices begin with, so a reader can
tell the operator did not type it; the block names the account and the phase.

Used by `hold_patrol.py` and `hold_continue.py`.
"""
from __future__ import annotations

from backend.jsonl.jsonl_predicates import CLIENT_NOTICE_OPENING as OPENING

TAG = "account-hold"
STOP = "stop"
CONTINUE = "continue"


def _attr(value: str) -> str:
    return value.replace('"', "'").replace("\n", " ")


def stop_envelope(account: str, account_name: str, *, both: bool = False) -> str:
    """The message that asks a tab that keeps answering, on an account at its hold line, to come to a break: the client
    puts it to sleep there. `both`: the tab's account has a fallback and both accounts are at their lines, so the client
    continues it by itself once either is clear."""
    reason, then = (("本来の口座も移す先の口座も使用量が線を超えたので", "どちらかの口座が線を下回った時に、client から")
                    if both else (f"{account_name} の口座の使用量が止める線を超えたので", "操作者が画面から続けた時に"))
    return (f'{OPENING}\n<{TAG} phase="{STOP}" account="{_attr(account)}">\n'
            f"{reason}、このタブを止めます。"
            f"今の作業を区切りの良い所まで進めて、この返事を終えてください。"
            f"続きは、{then}頼む連絡が届きます\n"
            f"</{TAG}>")


def continue_envelope(account: str, *, stopped: bool = True) -> str:
    """The message that asks a tab to carry on with what it was doing: one that was stopped (`stopped`), or one that
    was asked to come to a break and then was neither stopped nor moved."""
    body = ("止めていたタブを続けます。止める前の作業を続けてください" if stopped else
            "区切りを頼みましたが、止めずにこのまま続けます。頼む前の作業を続けてください")
    return (f'{OPENING}\n<{TAG} phase="{CONTINUE}" account="{_attr(account)}">\n'
            f"{body}\n"
            f"</{TAG}>")
