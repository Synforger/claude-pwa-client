"""ADR-012 inspector.snapshot の動作検証。 backend state にアクセスして dict を返す ベスト effort
路、 壊れた state でも 200 で返す設計を強制する。
"""
from __future__ import annotations

import pytest

from backend.observability import inspector
from backend.observability.inspector import _summarize_collection, snapshot


def test_summarize_collection_dict():
    result = _summarize_collection({"a": 1, "b": 2, "c": 3, "d": 4})
    assert result["type"] == "dict"
    assert result["size"] == 4
    assert len(result["keys_head"]) == 3


def test_summarize_collection_list():
    result = _summarize_collection([1, 2, 3, 4, 5])
    assert result["type"] == "list"
    assert result["size"] == 5
    assert result["head"] == [1, 2, 3]


def test_summarize_collection_set():
    result = _summarize_collection({1, 2, 3})
    assert result["type"] == "set"
    assert result["size"] == 3


def test_summarize_collection_non_collection_returns_none():
    assert _summarize_collection("string") is None
    assert _summarize_collection(42) is None


def test_summarize_collection_redacts_sensitive_in_list_head():
    result = _summarize_collection([{"api_key": "secret"}])
    assert result["head"][0]["api_key"] == "***"


def test_snapshot_returns_dict_with_expected_top_keys():
    snap = snapshot()
    assert isinstance(snap, dict)
    # backend state が取れない環境 (= test) でも何らかの key が入る
    assert "metrics" in snap
    assert "event_journal" in snap


def test_snapshot_includes_metrics_categories():
    snap = snapshot()
    if "metrics" in snap:
        assert set(snap["metrics"].keys()) >= {"counters", "gauges", "histograms"}


def test_snapshot_event_journal_has_current_seq():
    snap = snapshot()
    assert "current_seq" in snap.get("event_journal", {})
    assert isinstance(snap["event_journal"]["current_seq"], int)


def test_snapshot_does_not_raise_on_missing_backend_state(monkeypatch: pytest.MonkeyPatch):
    """import backend.state が失敗するように細工した場合でも snapshot は 200 path を返す。"""
    import sys

    original = sys.modules.get("backend.state")
    monkeypatch.setitem(sys.modules, "backend.state", None)  # import エラー誘発
    try:
        snap = snapshot()
        # backend state は取れないが、 他 field は埋まる
        assert isinstance(snap, dict)
        assert "backend_state_error" in snap or "metrics" in snap
    finally:
        if original is not None:
            sys.modules["backend.state"] = original
