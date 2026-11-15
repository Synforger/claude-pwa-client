"""The message the client sends the tab that wrote a kept message, when the kept message arrived, was refused, or was
dropped. The first line is the one the client's own notices begin with, so a reader can tell the operator did not type it.

Used by `outbox_flush.py`.
"""
from __future__ import annotations

from datetime import datetime

from backend.jsonl.jsonl_predicates import CLIENT_NOTICE_OPENING as OPENING
from backend.peers.outbox_judgement import EXPIRY_SEC, UNKNOWN_RECEIVER

TAG = "peer-outbox"
DELIVERED = "delivered"
REFUSED = "refused"
EXPIRED = "expired"

_HOUR_SEC = 3600


def _attr(value: str) -> str:
    return value.replace('"', "'").replace("\n", " ").replace("<", "&lt;")


def _sentence(event: str, entry: dict, detail: str) -> str:
    target = _attr(f"{entry['peer']}:{entry['to']}")
    kept_at = datetime.fromtimestamp(entry["kept_at"]).astimezone().strftime("%Y-%m-%d %H:%M")
    head = f"The message you sent to {target} at {kept_at} was kept because that machine did not answer."
    if event == DELIVERED:
        return f"{head} The machine is back and the message has arrived."
    if event == EXPIRED:
        return (f"{head} The machine did not come back within {EXPIRY_SEC // _HOUR_SEC} hours, so the message was "
                "dropped. Send it again when the machine is back.")
    return f"{head} The machine is back but refused it, so the message was dropped: {detail}"


def notice_envelope(event: str, entry: dict, detail: str = "", code: str = "") -> str:
    """The notice about the kept message `entry` (= `DELIVERED`, `REFUSED` with the other machine's code and words in
    `code` and `detail`, or `EXPIRED`)."""
    if code == UNKNOWN_RECEIVER:
        detail = "there is no such tab on that machine (it was renamed or closed)"
    target = _attr(f"{entry['peer']}:{entry['to']}")
    code_attribute = f' code="{_attr(code)}"' if code else ""
    return (f'{OPENING}\n<{TAG} event="{event}" to="{target}"{code_attribute}>\n'
            f"{_sentence(event, entry, detail)}\n"
            f"</{TAG}>")
