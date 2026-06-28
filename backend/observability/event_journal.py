"""ADR-012 event_journal: 全 SSE / WS event を per-day jsonl ファイルに shadow 記録する。

設計の核:
    - 1 day 1 file: `LOGS_DIR/event-journal/YYYY-MM-DD.jsonl`
    - 1 record = 1 行 JSON: `{seq, ts, sid, kind, event}` (= event は redact 適用済)
    - process 内 monotonic sequence (= replay の順序保証用、 process restart で 0 リセット)
    - rotation: GZIP_DAYS (= 1) 経過したら gzip 圧縮、 RETENTION_DAYS (= 14) で完全削除
    - disk watermark: 全 journal 合計が DISK_WATERMARK_MB (= 1GB) 超で最古 gzip を 1 件削除
    - thread safety: record() は threading.Lock で逐次化 (= SSE pump 並行呼び出し対応)
    - record() は redact を必ず通す (= secret が log に出ない構造保証、 ADR-012)

呼出例:
    from backend.observability.event_journal import record
    record(sid="ses_abc", kind="sse_user_message", event={"uuid": "u1", "text": "hi"})

rotate_and_purge() は backend/core/maintenance.py の loop から 1 日 1 回呼ぶ。
"""
from __future__ import annotations

import gzip
import json
import shutil
import threading
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from backend.paths import LOGS_DIR
from backend.observability.redact import redact

RETENTION_DAYS = 14
GZIP_DAYS = 1
DISK_WATERMARK_MB = 1024

JOURNAL_SUBDIR = "event-journal"
SUFFIX_JSONL = ".jsonl"
SUFFIX_GZIP = ".jsonl.gz"


class _Sequencer:
    """thread-safe monotonic sequence。 process restart で 0 リセット。

    将来 persistent sequence (= jsonl 末尾を読んで再開) に差し替える時もここを置き換えるだけで済む。
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._value = 0

    def next(self) -> int:
        with self._lock:
            self._value += 1
            return self._value

    def reset(self) -> None:
        """test 用。 production では呼ばない。"""
        with self._lock:
            self._value = 0

    def peek(self) -> int:
        with self._lock:
            return self._value


_sequencer = _Sequencer()
_write_lock = threading.Lock()


def _today() -> date:
    """UTC 日付を返す (= rotate / retention の境界を UTC で揃える、 timezone 跨ぎでも safe)。"""
    return datetime.now(timezone.utc).date()


def _journal_dir() -> Path:
    p = LOGS_DIR / JOURNAL_SUBDIR
    p.mkdir(parents=True, exist_ok=True)
    return p


def journal_path(d: date | None = None, gzipped: bool = False) -> Path:
    """指定日付の journal file path を返す (= 親 dir は ensure)。 d=None で今日。"""
    d = d or _today()
    suffix = SUFFIX_GZIP if gzipped else SUFFIX_JSONL
    return _journal_dir() / f"{d.isoformat()}{suffix}"


def _date_from_filename(p: Path) -> date | None:
    """`2026-06-28.jsonl` / `2026-06-28.jsonl.gz` から date を抽出 (= 不正名は None)。"""
    name = p.name
    if name.endswith(SUFFIX_GZIP):
        stem = name[: -len(SUFFIX_GZIP)]
    elif name.endswith(SUFFIX_JSONL):
        stem = name[: -len(SUFFIX_JSONL)]
    else:
        return None
    try:
        return date.fromisoformat(stem)
    except ValueError:
        return None


def record(sid: str, kind: str, event: Any, ts: float | None = None) -> int:
    """1 event を per-day jsonl に追記する。 返り値は採番された seq。

    - event は redact() を必ず通す (= secret 漏洩防止、 ADR-012)
    - ts 省略時は time.time() (= test では明示渡し可能)
    - write は threading.Lock で逐次化 (= SSE/WS 並行呼び出しでも 1 line per record)
    - I/O 失敗時は seq だけ消費して例外を投げる (= 呼出側で log warn、 production loop は exception 拾う)
    """
    seq = _sequencer.next()
    entry = {
        "seq": seq,
        "ts": ts if ts is not None else time.time(),
        "sid": sid,
        "kind": kind,
        "event": redact(event),
    }
    line = json.dumps(entry, ensure_ascii=False, separators=(",", ":")) + "\n"
    path = journal_path()
    with _write_lock:
        with path.open("a", encoding="utf-8") as f:
            f.write(line)
    return seq


def read_range(
    start_ts: float | None = None,
    end_ts: float | None = None,
    sid: str | None = None,
    today: date | None = None,
    days_back: int = 1,
) -> list[dict]:
    """直近 days_back 日分の journal を読み、 時刻 [start_ts, end_ts] + sid filter で entry を返す。

    replay.py から呼ばれる前提の helper。 gzip 圧縮済 file も透過的に読む。 巨大 file 想定でなく、
    debug / replay の探索用なので全行 in-memory load (= 数万行までは余裕)。 sequence 順は同日内で
    保証、 day 跨ぎは date 順で連結。
    """
    today = today or _today()
    out: list[dict] = []
    for offset in range(days_back, -1, -1):
        d = today - timedelta(days=offset)
        for path in (journal_path(d), journal_path(d, gzipped=True)):
            if not path.exists():
                continue
            opener = gzip.open if path.suffix == ".gz" else open
            with opener(path, "rt", encoding="utf-8") as f:
                for raw in f:
                    raw = raw.strip()
                    if not raw:
                        continue
                    try:
                        entry = json.loads(raw)
                    except json.JSONDecodeError:
                        continue
                    if sid is not None and entry.get("sid") != sid:
                        continue
                    ts = entry.get("ts")
                    if start_ts is not None and (ts is None or ts < start_ts):
                        continue
                    if end_ts is not None and (ts is None or ts > end_ts):
                        continue
                    out.append(entry)
    return out


def rotate_and_purge(today: date | None = None) -> dict[str, int]:
    """journal の rotation + retention + watermark を 1 回実行 (= maintenance_loop から daily)。

    動作:
        1. 過去日 (`today - GZIP_DAYS` 以前) の `.jsonl` を `.jsonl.gz` に変換、 元 `.jsonl` 削除
        2. 過去日 (`today - RETENTION_DAYS` 以前) の `.jsonl.gz` を削除
        3. journal_dir 合計が DISK_WATERMARK_MB 超なら最古 `.jsonl.gz` を 1 個削除して終了

    返り値 = `{gzipped, removed_retention, removed_watermark}` 件数 dict (= log / metrics 用)。
    """
    today = today or _today()
    journal_dir = _journal_dir()
    stats = {"gzipped": 0, "removed_retention": 0, "removed_watermark": 0}

    # 1) gzip 圧縮 (= GZIP_DAYS 経過 + 今日でない jsonl)
    for p in journal_dir.glob(f"*{SUFFIX_JSONL}"):
        d = _date_from_filename(p)
        if d is None:
            continue
        if (today - d).days > GZIP_DAYS:
            # `2026-06-26.jsonl` → `2026-06-26.jsonl.gz`。 with_suffix は最後の .xxx だけ置換する
            # 仕様なので、 multi-dot ".jsonl.gz" を直接 path 組立で表現する。
            gz = p.parent / (p.name + ".gz")
            try:
                with p.open("rb") as fi, gzip.open(gz, "wb") as fo:
                    shutil.copyfileobj(fi, fo)
                p.unlink()
                stats["gzipped"] += 1
            except OSError:
                # 同名 .gz 既存等は skip (= 次回 rotate で再試行)
                continue

    # 2) retention 超過 gz 削除
    for p in journal_dir.glob(f"*{SUFFIX_GZIP}"):
        d = _date_from_filename(p)
        if d is None:
            continue
        if (today - d).days > RETENTION_DAYS:
            try:
                p.unlink()
                stats["removed_retention"] += 1
            except OSError:
                continue

    # 3) disk watermark check (= 全体合計 size)
    total_bytes = 0
    for p in journal_dir.rglob("*"):
        if p.is_file():
            try:
                total_bytes += p.stat().st_size
            except OSError:
                continue
    if total_bytes > DISK_WATERMARK_MB * 1024 * 1024:
        # 最古の gz を 1 件削除 (= 「あふれた」 状況を構造的に解消、 過剰には消さない)
        gz_files = sorted(
            (p for p in journal_dir.glob(f"*{SUFFIX_GZIP}") if _date_from_filename(p) is not None),
            key=lambda p: _date_from_filename(p) or date.min,
        )
        if gz_files:
            try:
                gz_files[0].unlink()
                stats["removed_watermark"] += 1
            except OSError:
                # benign: watermark cleanup is best-effort; if unlink races with another
                # process we leave the file and the next maintenance tick retries.
                pass

    return stats


# test 用 export (= production では使わない)
__all__ = [
    "RETENTION_DAYS",
    "GZIP_DAYS",
    "DISK_WATERMARK_MB",
    "JOURNAL_SUBDIR",
    "journal_path",
    "record",
    "read_range",
    "rotate_and_purge",
    "_sequencer",
]
