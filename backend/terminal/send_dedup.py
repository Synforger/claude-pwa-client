"""The identity of one send (the `Idempotency-Key` HTTP header), for every door that types a message.

What it does:
    1. Dedup (`check_and_mark`): a second POST of the same (sid, send_id) is dropped before tmux is typed into.
    2. Binding to the conversation record (`bind_jsonl_uuid`): when the JSONL tail finds a new user row, its uuid is
       given to the oldest send of that sid that has none yet (first come by time, never by matching the text).
    3. Reverse lookup (`send_id_for_uuid`): the SSE `user_message` publisher finds the send_id of a jsonl uuid and
       puts it on the event.

Called by the send doors of `backend/terminal/routes.py` and by the JSONL publisher.

Two memories, both in process memory and lost on a restart:
    - The keys already typed (dedup). They are dropped only by count, oldest first, never by age. The screen posts a
      send again when its request got no answer (`frontend/src/features/chat/postSend.js`), and that request may have
      been typed before iOS cut the answer off while the app was behind. The repeat comes only when the app is in
      front again, after any length of time, so a memory that expires lets the repeat be typed a second time.
    - The candidates for binding: kept 60 s and at most 512, so a send that was typed but never became a user row
      does not take a later row's uuid.
A retry right after a restart is not deduped; `reconcileUserMessage` on the screen still pairs its bubble.
"""
from __future__ import annotations

import threading
import time
from collections import OrderedDict
from dataclasses import dataclass

_MAX_ENTRIES = 512
_TTL_SEC = 60.0
# Two short strings per key: the full memory stays under 1 MB.
_MAX_SEEN = 4096


@dataclass
class _Entry:
    sent_at: float
    jsonl_uuid: str | None = None


class SendDedup:
    def __init__(
        self, max_entries: int = _MAX_ENTRIES, ttl_sec: float = _TTL_SEC, *, max_seen: int = _MAX_SEEN
    ) -> None:
        self._entries: dict[tuple[str, str], _Entry] = {}
        self._seen: OrderedDict[tuple[str, str], None] = OrderedDict()
        self._max = max_entries
        self._ttl = ttl_sec
        self._max_seen = max_seen
        self._lock = threading.Lock()

    def check_and_mark(self, sid: str, send_id: str) -> bool:
        """Whether (sid, send_id) was typed already: True for a repeat (skip typing), else record it and return False.

        A repeat is caught however long after the first one it comes, until the key is pushed out by count.
        """
        with self._lock:
            key = (sid, send_id)
            if key in self._seen:
                return True
            self._seen[key] = None
            while len(self._seen) > self._max_seen:
                self._seen.popitem(last=False)
            self._purge_expired_locked()
            self._enforce_max_locked()
            self._entries[key] = _Entry(sent_at=time.monotonic())
            return False

    def bind_jsonl_uuid(self, sid: str, jsonl_uuid: str) -> str | None:
        """sid で未 mapping 最古の send_id に jsonl_uuid を焼く (= 時刻順先勝ち)。

        Returns:
            紐付けた send_id、 候補がなければ None。
        """
        with self._lock:
            self._purge_expired_locked()
            candidates = [
                (key, entry)
                for key, entry in self._entries.items()
                if key[0] == sid and entry.jsonl_uuid is None
            ]
            if not candidates:
                return None
            candidates.sort(key=lambda kv: kv[1].sent_at)
            key, entry = candidates[0]
            entry.jsonl_uuid = jsonl_uuid
            return key[1]

    def send_id_for_uuid(self, sid: str, jsonl_uuid: str) -> str | None:
        """(sid, jsonl_uuid) から send_id を逆引き。 SSE publisher が event に載せるため。"""
        with self._lock:
            for key, entry in self._entries.items():
                if key[0] == sid and entry.jsonl_uuid == jsonl_uuid:
                    return key[1]
            return None

    def _purge_expired_locked(self) -> None:
        now = time.monotonic()
        expired = [k for k, e in self._entries.items() if now - e.sent_at > self._ttl]
        for k in expired:
            del self._entries[k]

    def _enforce_max_locked(self) -> None:
        """entry 上限超過時、 最古の entry から捨てる。 通常は TTL purge で足りるが
        高頻度送信の burst 時の safety net。"""
        while len(self._entries) >= self._max:
            oldest_key = min(self._entries, key=lambda k: self._entries[k].sent_at)
            del self._entries[oldest_key]

    def reset(self) -> None:
        """test 用: 全 entry を消す。"""
        with self._lock:
            self._entries.clear()
            self._seen.clear()


send_dedup = SendDedup()
