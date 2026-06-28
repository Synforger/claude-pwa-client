"""ADR-012 event_journal: per-day jsonl + rotation + retention + watermark + redact 統合 の動作検証。

各 test は LOGS_DIR を一時 dir に差し替えてから動かす (= 実 logs/ を汚さない、 並列実行も衝突しない)。
"""
from __future__ import annotations

import gzip
import json
import threading
from datetime import date, timedelta
from pathlib import Path

import pytest

from backend.observability import event_journal as ej
from backend.observability.event_journal import (
    DISK_WATERMARK_MB,
    GZIP_DAYS,
    JOURNAL_SUBDIR,
    RETENTION_DAYS,
    journal_path,
    read_range,
    record,
    rotate_and_purge,
)


@pytest.fixture(autouse=True)
def _isolate_logs_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """LOGS_DIR を tmp_path に差し替え、 sequencer も毎回 0 リセット。"""
    monkeypatch.setattr(ej, "LOGS_DIR", tmp_path)
    ej._sequencer.reset()
    yield tmp_path


# --- record ---------------------------------------------------------------


def test_record_writes_one_line_with_seq_and_redact(_isolate_logs_dir):
    seq = record(sid="ses_abc", kind="sse_user_message", event={"text": "hi", "api_key": "secret"})
    assert seq == 1

    path = journal_path()
    assert path.exists()
    lines = path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
    entry = json.loads(lines[0])
    assert entry["seq"] == 1
    assert entry["sid"] == "ses_abc"
    assert entry["kind"] == "sse_user_message"
    # redact が適用されてる
    assert entry["event"]["api_key"] == "***"
    assert entry["event"]["text"] == "hi"
    assert isinstance(entry["ts"], float)


def test_record_sequence_monotonic_across_calls(_isolate_logs_dir):
    seqs = [record(sid="s", kind="k", event={"i": i}) for i in range(5)]
    assert seqs == [1, 2, 3, 4, 5]


def test_record_thread_safety_under_concurrent_writes(_isolate_logs_dir):
    """20 thread × 50 record で seq の連番性 + 1 行 per record を確認 (= Lock の効果)。"""
    N_THREADS = 20
    N_PER_THREAD = 50

    def worker(idx: int):
        for i in range(N_PER_THREAD):
            record(sid=f"s{idx}", kind="bench", event={"i": i})

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(N_THREADS)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    lines = journal_path().read_text(encoding="utf-8").splitlines()
    assert len(lines) == N_THREADS * N_PER_THREAD
    seqs = sorted(json.loads(l)["seq"] for l in lines)
    assert seqs == list(range(1, N_THREADS * N_PER_THREAD + 1))


def test_record_explicit_ts_is_honored(_isolate_logs_dir):
    record(sid="s", kind="k", event={}, ts=1700000000.5)
    entry = json.loads(journal_path().read_text(encoding="utf-8").splitlines()[0])
    assert entry["ts"] == 1700000000.5


def test_record_supports_japanese_event(_isolate_logs_dir):
    record(sid="s", kind="k", event={"msg": "日本語"})
    raw = journal_path().read_text(encoding="utf-8")
    assert "日本語" in raw  # ensure_ascii=False


# --- read_range ----------------------------------------------------------


def test_read_range_filters_by_sid_and_ts(_isolate_logs_dir):
    record(sid="A", kind="k", event={"i": 1}, ts=100.0)
    record(sid="B", kind="k", event={"i": 2}, ts=200.0)
    record(sid="A", kind="k", event={"i": 3}, ts=300.0)

    only_a = read_range(sid="A")
    assert [e["event"]["i"] for e in only_a] == [1, 3]

    in_window = read_range(start_ts=150.0, end_ts=250.0)
    assert [e["event"]["i"] for e in in_window] == [2]


def test_read_range_reads_from_gzipped_file(_isolate_logs_dir, tmp_path):
    """過去日付の .jsonl.gz も透過的に読める (= replay が gzip ファイルを扱えるか)。"""
    yesterday = ej._today() - timedelta(days=2)  # rotate されてるはずの日付
    plain = journal_path(yesterday)
    plain.write_text(json.dumps({"seq": 1, "ts": 50.0, "sid": "X", "kind": "old", "event": {"x": 1}}) + "\n",
                     encoding="utf-8")
    gz = journal_path(yesterday, gzipped=True)
    with plain.open("rb") as fi, gzip.open(gz, "wb") as fo:
        fo.write(fi.read())
    plain.unlink()

    out = read_range(today=ej._today(), days_back=3, sid="X")
    assert len(out) == 1
    assert out[0]["event"]["x"] == 1


# --- rotate_and_purge ----------------------------------------------------


def test_rotate_gzips_files_older_than_gzip_days(_isolate_logs_dir):
    today = date(2026, 6, 28)
    old_day = today - timedelta(days=GZIP_DAYS + 1)
    p = journal_path(old_day)
    p.write_text("{\"seq\":1}\n", encoding="utf-8")

    stats = rotate_and_purge(today=today)
    assert stats["gzipped"] == 1
    assert not p.exists()
    assert journal_path(old_day, gzipped=True).exists()


def test_rotate_skips_today_and_within_gzip_window(_isolate_logs_dir):
    today = date(2026, 6, 28)
    today_p = journal_path(today)
    today_p.write_text("{\"seq\":1}\n", encoding="utf-8")
    within_p = journal_path(today - timedelta(days=GZIP_DAYS))
    within_p.write_text("{\"seq\":2}\n", encoding="utf-8")

    stats = rotate_and_purge(today=today)
    assert stats["gzipped"] == 0
    assert today_p.exists() and within_p.exists()


def test_rotate_purges_gz_older_than_retention(_isolate_logs_dir):
    today = date(2026, 6, 28)
    too_old = today - timedelta(days=RETENTION_DAYS + 5)
    gz = journal_path(too_old, gzipped=True)
    gz.write_bytes(b"\x1f\x8bdummy")  # gz っぽい中身 (= 削除には中身正当性は無関係)

    stats = rotate_and_purge(today=today)
    assert stats["removed_retention"] == 1
    assert not gz.exists()


def test_rotate_keeps_gz_within_retention(_isolate_logs_dir):
    today = date(2026, 6, 28)
    fresh = today - timedelta(days=RETENTION_DAYS - 1)
    gz = journal_path(fresh, gzipped=True)
    gz.write_bytes(b"\x1f\x8bdummy")

    stats = rotate_and_purge(today=today)
    assert stats["removed_retention"] == 0
    assert gz.exists()


def test_rotate_watermark_removes_oldest_gz_when_over_limit(_isolate_logs_dir, monkeypatch: pytest.MonkeyPatch):
    """DISK_WATERMARK_MB を低い値に差し替え、 oldest gz が 1 件削除されるか確認。"""
    monkeypatch.setattr(ej, "DISK_WATERMARK_MB", 0)  # 即 over とみなす
    today = date(2026, 6, 28)
    older = journal_path(today - timedelta(days=3), gzipped=True)
    newer = journal_path(today - timedelta(days=2), gzipped=True)
    older.write_bytes(b"a" * 100)
    newer.write_bytes(b"b" * 100)

    stats = rotate_and_purge(today=today)
    assert stats["removed_watermark"] == 1
    assert not older.exists()
    assert newer.exists()


def test_rotate_idempotent_on_empty_dir(_isolate_logs_dir):
    today = date(2026, 6, 28)
    stats = rotate_and_purge(today=today)
    assert stats == {"gzipped": 0, "removed_retention": 0, "removed_watermark": 0}


def test_journal_subdir_constant_used(_isolate_logs_dir):
    """journal_path() が LOGS_DIR/JOURNAL_SUBDIR/<date>.jsonl で組まれる。"""
    p = journal_path(date(2026, 6, 28))
    assert p.parent.name == JOURNAL_SUBDIR
    assert p.name == "2026-06-28.jsonl"
