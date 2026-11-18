"""Lets a log line through at most once per interval for each (kind, reason), so a file that stays broken does not write
a line every half second. Used by `api_tab_stream.py`.
"""
from __future__ import annotations

import time


class LogThrottle:
    """Remembers when each (kind, reason) was last let through."""

    def __init__(self, interval_sec: float) -> None:
        self._interval_sec = interval_sec
        self._last: dict[tuple[str, str], float] = {}

    def allows(self, kind: str, reason: str, *, now: float | None = None) -> bool:
        """Whether a line for `kind` with this `reason` may be written now; true also records it as written."""
        now = time.monotonic() if now is None else now
        last = self._last.get((kind, reason))
        if last is not None and now - last < self._interval_sec:
            return False
        self._last[(kind, reason)] = now
        return True

    def forget(self, kind: str) -> None:
        """Forget every reason of `kind`, so the next trouble of it is written at once (= after it was put right)."""
        for key in [key for key in self._last if key[0] == kind]:
            del self._last[key]
