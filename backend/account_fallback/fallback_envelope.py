"""The messages the account fallback sends a tab: the request to come to a break before it is moved (to its fallback
account, or back to its own), and the request to carry on once it has been moved (because a usage limit stopped it, or
because it came to the break it was asked for). The first line is the one the client's own notices begin with, so a reader can tell the operator did not type
it; the block names the move and the reason.

Used by `fallback_patrol.py`.
"""
from __future__ import annotations

from backend.jsonl.jsonl_predicates import CLIENT_NOTICE_OPENING as OPENING

TAG = "account-move"
LIMIT = "limit"
PAUSE = "pause"

_CARRY_ON_BODY = {
    LIMIT: ("A usage limit stopped this session, so the client moved it to another account. "
            "Carry on with the work you were doing before it stopped."),
    PAUSE: "口座を移しました。止める前の作業を続けてください",
}


def _attr(value: str) -> str:
    return value.replace('"', "'").replace("\n", " ")


def carry_on_envelope(from_account: str, to_account: str, reason: str = LIMIT) -> str:
    """The message that asks a tab, moved after its work was stopped (`reason` = `LIMIT`) or after it was asked to
    come to a break (`PAUSE`), to carry on."""
    return (f'{OPENING}\n<{TAG} from="{_attr(from_account)}" to="{_attr(to_account)}" reason="{_attr(reason)}">\n'
            f"{_CARRY_ON_BODY[reason]}\n"
            f"</{TAG}>")


def return_pause_envelope(from_account: str, to_account: str, from_name: str, to_name: str) -> str:
    """The message that asks a tab that keeps answering, on an account that has reached its line, to come to a break:
    the client moves it back to `to_name`'s account (= its own) there."""
    return (f'{OPENING}\n<{TAG} phase="{PAUSE}" from="{_attr(from_account)}" to="{_attr(to_account)}">\n'
            f"{from_name} の口座の使用量が線を超えたので、このタブを {to_name} の口座へ戻します。"
            f"今の作業を区切りの良い所まで進めて、この返事を終えてください。"
            f"戻した後に、続きを頼む連絡が届きます\n"
            f"</{TAG}>")


def pause_envelope(from_account: str, to_account: str, to_name: str) -> str:
    """The message that asks a tab that keeps answering, on an account at its line, to come to a break: the client
    moves it to `to_name`'s account there."""
    return (f'{OPENING}\n<{TAG} phase="{PAUSE}" from="{_attr(from_account)}" to="{_attr(to_account)}">\n'
            f"使用量が線を超えたので、このタブを {to_name} の口座へ移します。"
            f"今の作業を区切りの良い所まで進めて、この返事を終えてください。"
            f"移した後に、続きを頼む連絡が届きます\n"
            f"</{TAG}>")
