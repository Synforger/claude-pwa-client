"""backend.jsonl.history の単体テスト (= MAX_ENTRIES 制限 / dedup / persist 経路)。"""
from __future__ import annotations

import json


def test_record_and_get(monkeypatch, tmp_path):
    from backend.jsonl import history

    monkeypatch.setattr(history, "SESSION_HISTORY_PATH", tmp_path / "session_history.json")

    history.record_end("ses_x", "claude-aaa", jsonl_path="/p/aaa.jsonl")
    history.record_end("ses_x", "claude-bbb", jsonl_path="/p/bbb.jsonl")

    entries = history.get("ses_x")
    assert len(entries) == 2
    # 新しい順
    assert entries[0]["claude_sid"] == "claude-bbb"
    assert entries[1]["claude_sid"] == "claude-aaa"
    assert entries[0]["jsonl_path"] == "/p/bbb.jsonl"
    assert isinstance(entries[0]["ended_at"], int)


def test_max_entries_cap_at_3(monkeypatch, tmp_path):
    from backend.jsonl import history

    monkeypatch.setattr(history, "SESSION_HISTORY_PATH", tmp_path / "session_history.json")

    for i in range(5):
        history.record_end("ses_x", f"claude-{i}")

    entries = history.get("ses_x")
    assert len(entries) == 3
    # 新しい順 (= 直近 3 件 = 4, 3, 2)
    assert [e["claude_sid"] for e in entries] == ["claude-4", "claude-3", "claude-2"]


def test_dedup_consecutive_same_sid(monkeypatch, tmp_path):
    from backend.jsonl import history

    monkeypatch.setattr(history, "SESSION_HISTORY_PATH", tmp_path / "session_history.json")

    history.record_end("ses_x", "claude-aaa")
    history.record_end("ses_x", "claude-aaa")  # 同じ id 連投は無視
    history.record_end("ses_x", "claude-aaa")

    assert len(history.get("ses_x")) == 1


def test_none_or_empty_is_noop(monkeypatch, tmp_path):
    from backend.jsonl import history

    monkeypatch.setattr(history, "SESSION_HISTORY_PATH", tmp_path / "session_history.json")

    history.record_end("ses_x", None)
    history.record_end("", "claude-aaa")

    assert history.get("ses_x") == []
    assert not (tmp_path / "session_history.json").exists()


def test_isolation_between_pwa_sids(monkeypatch, tmp_path):
    from backend.jsonl import history

    monkeypatch.setattr(history, "SESSION_HISTORY_PATH", tmp_path / "session_history.json")

    history.record_end("ses_a", "claude-a1")
    history.record_end("ses_b", "claude-b1")
    history.record_end("ses_a", "claude-a2")

    assert [e["claude_sid"] for e in history.get("ses_a")] == ["claude-a2", "claude-a1"]
    assert [e["claude_sid"] for e in history.get("ses_b")] == ["claude-b1"]


def test_persists_to_disk(monkeypatch, tmp_path):
    from backend.jsonl import history

    path = tmp_path / "session_history.json"
    monkeypatch.setattr(history, "SESSION_HISTORY_PATH", path)

    history.record_end("ses_x", "claude-aaa")

    raw = json.loads(path.read_text())
    assert raw["ses_x"][0]["claude_sid"] == "claude-aaa"


def test_corrupt_file_starts_fresh(monkeypatch, tmp_path):
    from backend.jsonl import history

    path = tmp_path / "session_history.json"
    path.write_text("not json")
    monkeypatch.setattr(history, "SESSION_HISTORY_PATH", path)

    history.record_end("ses_x", "claude-aaa")

    assert [e["claude_sid"] for e in history.get("ses_x")] == ["claude-aaa"]
