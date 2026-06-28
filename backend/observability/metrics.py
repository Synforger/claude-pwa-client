"""in-memory metrics counter / gauge / histogram。 /debug/metrics endpoint で export する。

設計の核:
    - counter:   monotonic な累計値 (= 接続数 / event 数 / error 数 等)
    - gauge:     その瞬間の値 (= queue size / 接続中 sse / 接続中 ws)
    - histogram: 直近 N サンプルから p50 / p95 / max を返す (= latency)
    - reset(): test 用、 production では呼ばない

threading.Lock で並列 safe。 production の SSE / WS pump は asyncio だが GIL + Lock で問題なし。
"""
from __future__ import annotations

import threading
from collections import defaultdict, deque


class _Metrics:
    """全 counter / gauge / histogram を 1 instance に集約する registry。"""

    HISTOGRAM_WINDOW = 256  # 直近 N サンプル

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._counters: dict[str, float] = defaultdict(float)
        self._gauges: dict[str, float] = {}
        self._histograms: dict[str, deque[float]] = defaultdict(lambda: deque(maxlen=self.HISTOGRAM_WINDOW))

    # --- counter ---------------------------------------------------------

    def inc(self, name: str, amount: float = 1.0) -> None:
        with self._lock:
            self._counters[name] += amount

    def counter(self, name: str) -> float:
        with self._lock:
            return self._counters.get(name, 0.0)

    # --- gauge -----------------------------------------------------------

    def set_gauge(self, name: str, value: float) -> None:
        with self._lock:
            self._gauges[name] = value

    def gauge(self, name: str) -> float | None:
        with self._lock:
            return self._gauges.get(name)

    # --- histogram -------------------------------------------------------

    def observe(self, name: str, value: float) -> None:
        with self._lock:
            self._histograms[name].append(value)

    def percentile(self, name: str, p: float) -> float | None:
        """p は 0.0 - 1.0 (= 0.5 → p50)。 サンプル 0 の時 None。"""
        with self._lock:
            samples = list(self._histograms.get(name, ()))
        if not samples:
            return None
        if not 0.0 <= p <= 1.0:
            raise ValueError(f"percentile p must be in [0, 1], got {p}")
        samples.sort()
        # 0-index ベース (= numpy.percentile interpolation='lower' と同等)。
        # 1..N のサンプルで p=0.5 のとき index = 0.5*(N-1) → N=100 で index=49 → 値 50。
        n = len(samples)
        idx = min(int(p * (n - 1)), n - 1)
        return samples[idx]

    def histogram_summary(self, name: str) -> dict[str, float | int | None]:
        """`{count, p50, p95, p99, max}` を返す (= /debug/metrics で読みやすい形)。"""
        with self._lock:
            samples = list(self._histograms.get(name, ()))
        if not samples:
            return {"count": 0, "p50": None, "p95": None, "p99": None, "max": None}
        s = sorted(samples)
        n = len(s)

        def pct(p: float) -> float:
            return s[min(int(p * (n - 1)), n - 1)]

        return {
            "count": n,
            "p50": pct(0.5),
            "p95": pct(0.95),
            "p99": pct(0.99),
            "max": s[-1],
        }

    # --- export / reset -------------------------------------------------

    def snapshot(self) -> dict[str, object]:
        """全 counter / gauge / histogram を dict で返す (= /debug/metrics 用)。"""
        with self._lock:
            counters = dict(self._counters)
            gauges = dict(self._gauges)
            hist_keys = list(self._histograms.keys())
        histograms = {k: self.histogram_summary(k) for k in hist_keys}
        return {
            "counters": counters,
            "gauges": gauges,
            "histograms": histograms,
        }

    def reset(self) -> None:
        """test 用にだけ使う、 production では呼ばない。"""
        with self._lock:
            self._counters.clear()
            self._gauges.clear()
            self._histograms.clear()


metrics = _Metrics()


# --- 標準カウンター名 (= ADR-012 の queue size / reconnect / latency / error rate) ---

# SSE
SSE_CONNECTIONS_OPENED = "sse.connections.opened"
SSE_CONNECTIONS_ACTIVE = "sse.connections.active"
SSE_EVENTS_EMITTED = "sse.events.emitted"
SSE_RECONNECTS = "sse.reconnects"

# WS
WS_CONNECTIONS_OPENED = "ws.connections.opened"
WS_CONNECTIONS_ACTIVE = "ws.connections.active"
WS_FRAMES_RECEIVED = "ws.frames.received"
WS_FRAMES_SENT = "ws.frames.sent"
WS_RECONNECTS = "ws.reconnects"
WS_HEARTBEAT_TIMEOUTS = "ws.heartbeat.timeouts"

# HTTP
HTTP_REQUESTS = "http.requests"
HTTP_ERRORS_5XX = "http.errors.5xx"
HTTP_ERRORS_4XX = "http.errors.4xx"
HTTP_LATENCY_MS = "http.latency.ms"  # histogram

# Queue
QUEUE_BACKLOG = "queue.backlog"  # gauge (broadcaster 等)

# Event journal
JOURNAL_RECORDED = "journal.recorded"
JOURNAL_ROTATE_GZIPPED = "journal.rotate.gzipped"
JOURNAL_ROTATE_REMOVED = "journal.rotate.removed"


__all__ = [
    "metrics",
    "_Metrics",
    "SSE_CONNECTIONS_OPENED",
    "SSE_CONNECTIONS_ACTIVE",
    "SSE_EVENTS_EMITTED",
    "SSE_RECONNECTS",
    "WS_CONNECTIONS_OPENED",
    "WS_CONNECTIONS_ACTIVE",
    "WS_FRAMES_RECEIVED",
    "WS_FRAMES_SENT",
    "WS_RECONNECTS",
    "WS_HEARTBEAT_TIMEOUTS",
    "HTTP_REQUESTS",
    "HTTP_ERRORS_5XX",
    "HTTP_ERRORS_4XX",
    "HTTP_LATENCY_MS",
    "QUEUE_BACKLOG",
    "JOURNAL_RECORDED",
    "JOURNAL_ROTATE_GZIPPED",
    "JOURNAL_ROTATE_REMOVED",
]
