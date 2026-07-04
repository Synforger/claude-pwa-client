"""送信の identity (= `Idempotency-Key` HTTP header) を全経路で扱う module。

責務:
    1. dedup 判定 (= `check_and_mark`): 同一 (sid, send_id) の 2 発目 POST を tmux 打鍵前に drop
    2. JSONL uuid 対応付け (= `bind_jsonl_uuid`): JSONL tail が新 user 行を検出した時、
       その sid の「未 mapping 最古 send_id」 に uuid を焼く (= text 一致は使わず時刻順先勝ち)
    3. 逆引き (= `send_id_for_uuid`): SSE `user_message` event publisher が jsonl_uuid から
       送信元 send_id を引いて event に載せる

設計:
    - inmemory LRU、 TTL 60s、 memory bounded (= 最大 512 entry)
    - process restart で消える = 揮発、 restart 直後の client retry は dedup 抜ける
      (frontend `reconcileUserMessage` の近傍 fallback で救う二層構造)
    - text 一致は使わない (= 「時刻順に最古の未 mapping」 で先勝ち) ので同一 text 連投でも
      対応付けが決定的
"""
from __future__ import annotations

import threading
import time
from dataclasses import dataclass

_MAX_ENTRIES = 512
_TTL_SEC = 60.0


@dataclass
class _Entry:
    sent_at: float
    jsonl_uuid: str | None = None


class SendDedup:
    def __init__(self, max_entries: int = _MAX_ENTRIES, ttl_sec: float = _TTL_SEC) -> None:
        self._entries: dict[tuple[str, str], _Entry] = {}
        self._max = max_entries
        self._ttl = ttl_sec
        self._lock = threading.Lock()

    def check_and_mark(self, sid: str, send_id: str) -> bool:
        """(sid, send_id) が既登録なら True (= 2 発目、 tmux 打鍵 skip)、
        新規なら登録して False を返す。"""
        with self._lock:
            self._purge_expired_locked()
            key = (sid, send_id)
            if key in self._entries:
                return True
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


send_dedup = SendDedup()
