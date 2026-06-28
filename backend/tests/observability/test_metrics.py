"""ADR-012 metrics: counter / gauge / histogram の動作検証。"""
from __future__ import annotations

import threading

import pytest

from backend.observability.metrics import (
    HTTP_LATENCY_MS,
    HTTP_REQUESTS,
    SSE_CONNECTIONS_ACTIVE,
    _Metrics,
    metrics,
)


@pytest.fixture
def m():
    instance = _Metrics()
    yield instance


def test_counter_increments(m: _Metrics):
    m.inc("foo")
    m.inc("foo", 3)
    assert m.counter("foo") == 4


def test_counter_default_zero(m: _Metrics):
    assert m.counter("never_touched") == 0


def test_gauge_set_and_read(m: _Metrics):
    m.set_gauge(SSE_CONNECTIONS_ACTIVE, 7)
    assert m.gauge(SSE_CONNECTIONS_ACTIVE) == 7
    m.set_gauge(SSE_CONNECTIONS_ACTIVE, 3)
    assert m.gauge(SSE_CONNECTIONS_ACTIVE) == 3
    assert m.gauge("never_set") is None


def test_histogram_percentile_basic(m: _Metrics):
    for v in range(1, 101):  # 1..100
        m.observe(HTTP_LATENCY_MS, v)
    assert m.percentile(HTTP_LATENCY_MS, 0.5) == 50
    assert m.percentile(HTTP_LATENCY_MS, 0.95) == 95
    assert m.percentile(HTTP_LATENCY_MS, 1.0) == 100


def test_histogram_summary_shape(m: _Metrics):
    for v in [10, 20, 30, 40, 50]:
        m.observe("h", v)
    s = m.histogram_summary("h")
    assert s["count"] == 5
    assert s["max"] == 50
    assert s["p50"] is not None
    assert s["p95"] is not None
    assert s["p99"] is not None


def test_histogram_summary_empty(m: _Metrics):
    s = m.histogram_summary("never")
    assert s == {"count": 0, "p50": None, "p95": None, "p99": None, "max": None}


def test_histogram_window_keeps_only_last_n(m: _Metrics):
    """HISTOGRAM_WINDOW 超のサンプルは古い順に捨てられる。"""
    n = m.HISTOGRAM_WINDOW
    for v in range(n + 50):
        m.observe("rolling", v)
    s = m.histogram_summary("rolling")
    assert s["count"] == n
    # 最後の n 件しか残らない (= 50 以降)
    assert s["max"] == n + 50 - 1


def test_percentile_rejects_invalid_p(m: _Metrics):
    m.observe("h", 1)
    with pytest.raises(ValueError):
        m.percentile("h", -0.1)
    with pytest.raises(ValueError):
        m.percentile("h", 1.5)


def test_percentile_none_for_empty_histogram(m: _Metrics):
    assert m.percentile("empty", 0.5) is None


def test_snapshot_includes_all_categories(m: _Metrics):
    m.inc("c.foo", 5)
    m.set_gauge("g.bar", 7)
    m.observe("h.baz", 12)
    snap = m.snapshot()
    assert snap["counters"]["c.foo"] == 5
    assert snap["gauges"]["g.bar"] == 7
    assert snap["histograms"]["h.baz"]["count"] == 1
    assert snap["histograms"]["h.baz"]["max"] == 12


def test_reset_clears_everything(m: _Metrics):
    m.inc("c")
    m.set_gauge("g", 1)
    m.observe("h", 1)
    m.reset()
    snap = m.snapshot()
    assert snap == {"counters": {}, "gauges": {}, "histograms": {}}


def test_concurrent_counter_increment_is_safe(m: _Metrics):
    """100 thread × 1000 inc の合計が一致 (= Lock の効果)。"""
    N_THREADS = 100
    N_INC = 1000

    def worker():
        for _ in range(N_INC):
            m.inc("hot")

    threads = [threading.Thread(target=worker) for _ in range(N_THREADS)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert m.counter("hot") == N_THREADS * N_INC


def test_module_level_metrics_singleton():
    """module top-level `metrics` は singleton として使える (= production の registry)。"""
    metrics.reset()
    metrics.inc(HTTP_REQUESTS)
    assert metrics.counter(HTTP_REQUESTS) == 1
    metrics.reset()
