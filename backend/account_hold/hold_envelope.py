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


def stop_envelope(account: str, account_name: str) -> str:
    """The message that asks a tab that keeps answering, on an account at its hold line, to come to a break: the client
    puts it to sleep there."""
    return (f'{OPENING}\n<{TAG} phase="{STOP}" account="{_attr(account)}">\n'
            f"{account_name} の口座の使用量が止める線を超えたので、このタブを止めます。"
            f"今の作業を区切りの良い所まで進めて、この返事を終えてください。"
            f"続きは、操作者が画面から続けた時に頼む連絡が届きます\n"
            f"</{TAG}>")


def continue_envelope(account: str) -> str:
    """The message that asks a tab the operator continues to carry on with what it was doing before it was stopped."""
    return (f'{OPENING}\n<{TAG} phase="{CONTINUE}" account="{_attr(account)}">\n'
            f"止めていたタブを続けます。止める前の作業を続けてください\n"
            f"</{TAG}>")
