"""What a machine's record says and how to tell the sender: no file, no network, no clock of its own.

Used by `peer_health.py` (the next record), `peer_send.py` and `outbox_flush.py` (the words for the sender).
"""
from __future__ import annotations

from datetime import datetime, timezone

# Why a message was kept (= `reason` of the answer), and the end of the code of the error when it could not be kept.
PEER_OFFLINE = "peer_offline"
PEER_UNREACHABLE = "peer_unreachable"
# The reason of a message kept only because earlier ones for the same machine are still waiting.
EARLIER_WAITING = "earlier_waiting"

_ERROR_CODE_PREFIX = "agent_message_"
_MINUTE_SEC = 60
_HOUR_SEC = 3600


def next_record(previous: dict | None, *, ok: bool, error: str | None, tailnet: dict, now: datetime) -> dict:
    """The record of a machine after a look. `since` is when it came to be in its present state (= answering or not):
    it stays while the state does."""
    stamp = now.astimezone(timezone.utc).isoformat(timespec="seconds")
    unchanged = previous is not None and previous.get("ok") == ok and isinstance(previous.get("since"), str)
    return {"ok": ok, "since": previous["since"] if unchanged else stamp, "checked_at": stamp,
            "last_error": error, "tailnet": {"online": tailnet.get("online"), "last_seen": tailnet.get("last_seen")}}


def reason_of(record: dict | None) -> str:
    """Why a machine that did not answer keeps its messages waiting: it is off the tailnet, or it is on it (or that
    cannot be told) and does not answer."""
    online = ((record or {}).get("tailnet") or {}).get("online")
    return PEER_OFFLINE if online is False else PEER_UNREACHABLE


def error_code(record: dict | None) -> str:
    """The code of the error a message gets when it could not be kept either."""
    return _ERROR_CODE_PREFIX + reason_of(record)


def _ago(then: datetime, now: datetime) -> str:
    seconds = max(0, int((now - then).total_seconds()))
    if seconds < _HOUR_SEC:
        return f"{max(1, seconds // _MINUTE_SEC)} 分前"
    return f"{seconds // _HOUR_SEC} 時間前"


def _last_seen_text(last_seen: str | None, now: datetime) -> str:
    try:
        seen = datetime.fromisoformat(last_seen) if last_seen else None
    except ValueError:
        seen = None
    if seen is None or seen.tzinfo is None:
        return "最後に見えた時刻は分かりません"
    return f"最後に見えたのは {seen.astimezone().strftime('%Y-%m-%d %H:%M')} ({_ago(seen, now)})"


def unreachable_message(name: str, record: dict | None, now: datetime) -> str:
    """The sentence for the sender about a machine that did not answer."""
    tailnet = (record or {}).get("tailnet") or {}
    if tailnet.get("online") is False:
        return (f"{name} の機械は tailnet に出ていません。 {_last_seen_text(tailnet.get('last_seen'), now)}。 "
                "眠っているか、 電源か網が落ちています")
    if tailnet.get("online") is True:
        return f"{name} の機械は tailnet には出ていますが、 client の backend が答えません"
    return f"{name} の機械に繋がりませんでした"
