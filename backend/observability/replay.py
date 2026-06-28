"""ADR-012 replay: event_journal を時刻区間で SSE 再配信する。

設計の核:
    - read_range で {start_ts, end_ts, sid} に該当する entry を集める
    - sequence id 順 (= record() で採番された monotonic) でソート
    - speed > 0 なら entry 間の ts 差分 / speed 待ち (= 1.0 でリアルタイム、 1000 で高速)
    - speed == 0 で間隔ゼロ (= 全件即流し、 test / バックフィル用途)
    - generator は SSE frame 文字列を yield、 呼出側 (= /debug/replay) で StreamingResponse に
"""
from __future__ import annotations

import asyncio
import json
from typing import AsyncIterator

from backend.observability.event_journal import read_range


def _sse_frame(entry: dict) -> str:
    """1 entry を SSE frame 文字列に変換 (= /jsonl/stream/* と同じ形式)。

    `id:` は entry の seq、 `data:` は event 本体 (= record() 時に redact 済の dict)。 frontend
    debug panel が `lastEventId` を読んで途中再開できるよう seq を載せる。
    """
    seq = entry.get("seq")
    event = entry.get("event", {})
    # 再配信時も backend 共通の envelope (= sid + corr_id) を尊重 (= 元 event がそのまま持ってる)
    payload = {"sid": entry.get("sid"), "kind": entry.get("kind"), "event": event, "replay_ts": entry.get("ts")}
    return f"id: {seq}\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"


async def replay_stream(
    sid: str | None = None,
    start_ts: float | None = None,
    end_ts: float | None = None,
    speed: float = 0.0,
    days_back: int = 1,
    _sleep=asyncio.sleep,
) -> AsyncIterator[str]:
    """指定区間の entry を SSE frame として yield する async generator。

    速度制御:
        - speed == 0: 待たない (= 全件即流し)
        - speed > 0: entry 間隔を (next_ts - prev_ts) / speed 秒だけ sleep
        - speed < 0: ValueError

    `_sleep` は test 注入用 (= production では asyncio.sleep 固定)。
    """
    if speed < 0:
        raise ValueError(f"speed must be >= 0, got {speed}")

    entries = read_range(start_ts=start_ts, end_ts=end_ts, sid=sid, days_back=days_back)
    entries.sort(key=lambda e: (e.get("seq", 0)))

    prev_ts: float | None = None
    for entry in entries:
        ts = entry.get("ts")
        if speed > 0 and prev_ts is not None and isinstance(ts, (int, float)):
            delta = (ts - prev_ts) / speed
            if delta > 0:
                await _sleep(delta)
        yield _sse_frame(entry)
        if isinstance(ts, (int, float)):
            prev_ts = ts


async def collect_replay(
    sid: str | None = None,
    start_ts: float | None = None,
    end_ts: float | None = None,
    days_back: int = 1,
) -> list[str]:
    """test 用: replay_stream 全件を list で受ける (= 待たず speed=0)。"""
    out: list[str] = []
    async for frame in replay_stream(sid=sid, start_ts=start_ts, end_ts=end_ts, speed=0.0, days_back=days_back):
        out.append(frame)
    return out


__all__ = ["replay_stream", "collect_replay"]
