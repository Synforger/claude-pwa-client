"""ADR-012 replay: event_journal を時刻区間 + sid で SSE 再配信する非同期 generator の動作検証。"""
from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from backend.observability import event_journal as ej
from backend.observability.event_journal import record
from backend.observability.replay import collect_replay, replay_stream


@pytest.fixture(autouse=True)
def _isolate_logs_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(ej, "LOGS_DIR", tmp_path)
    ej._sequencer.reset()
    yield tmp_path


def _run_async(coro):
    """asyncio.run の MainThread loop policy 破壊回避 (= test_correlation と同じ流儀)。"""
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()
        asyncio.set_event_loop(asyncio.new_event_loop())


def test_replay_orders_by_sequence_id():
    """ts が逆順でも seq 順に流す (= record() の monotonic 性に従う)。"""
    record(sid="s", kind="k", event={"i": 1}, ts=100.0)
    record(sid="s", kind="k", event={"i": 2}, ts=50.0)
    record(sid="s", kind="k", event={"i": 3}, ts=200.0)

    frames = _run_async(collect_replay())
    payloads = [json.loads(f.split("data: ", 1)[1].split("\n\n", 1)[0]) for f in frames]
    assert [p["event"]["i"] for p in payloads] == [1, 2, 3]


def test_replay_filter_by_sid():
    record(sid="A", kind="k", event={"i": 1})
    record(sid="B", kind="k", event={"i": 2})
    record(sid="A", kind="k", event={"i": 3})

    frames = _run_async(collect_replay(sid="A"))
    payloads = [json.loads(f.split("data: ", 1)[1].split("\n\n", 1)[0]) for f in frames]
    assert [p["event"]["i"] for p in payloads] == [1, 3]
    assert all(p["sid"] == "A" for p in payloads)


def test_replay_filter_by_ts_window():
    record(sid="s", kind="k", event={"i": 1}, ts=100.0)
    record(sid="s", kind="k", event={"i": 2}, ts=200.0)
    record(sid="s", kind="k", event={"i": 3}, ts=300.0)

    frames = _run_async(collect_replay(start_ts=150.0, end_ts=250.0))
    payloads = [json.loads(f.split("data: ", 1)[1].split("\n\n", 1)[0]) for f in frames]
    assert [p["event"]["i"] for p in payloads] == [2]


def test_replay_includes_seq_in_sse_id():
    record(sid="s", kind="k", event={})
    frames = _run_async(collect_replay())
    assert frames[0].startswith("id: 1\n")


def test_replay_includes_kind_and_replay_ts():
    record(sid="s", kind="sse_user_message", event={"text": "hi"}, ts=42.0)
    frames = _run_async(collect_replay())
    payload = json.loads(frames[0].split("data: ", 1)[1].split("\n\n", 1)[0])
    assert payload["kind"] == "sse_user_message"
    assert payload["replay_ts"] == 42.0


def test_replay_empty_when_no_entries():
    frames = _run_async(collect_replay())
    assert frames == []


def test_replay_speed_zero_does_not_sleep():
    record(sid="s", kind="k", event={}, ts=0.0)
    record(sid="s", kind="k", event={}, ts=100.0)  # 100 秒間隔

    slept = []

    async def fake_sleep(d):
        slept.append(d)

    async def drive():
        frames = []
        async for f in replay_stream(speed=0.0, _sleep=fake_sleep):
            frames.append(f)
        return frames

    frames = _run_async(drive())
    assert len(frames) == 2
    assert slept == []


def test_replay_speed_one_sleeps_full_delta():
    record(sid="s", kind="k", event={}, ts=0.0)
    record(sid="s", kind="k", event={}, ts=2.5)

    slept = []

    async def fake_sleep(d):
        slept.append(d)

    async def drive():
        return [f async for f in replay_stream(speed=1.0, _sleep=fake_sleep)]

    _run_async(drive())
    # 1 個目は prev_ts None なので sleep なし、 2 個目は (2.5 - 0.0)/1.0 = 2.5
    assert slept == [2.5]


def test_replay_speed_high_compresses_intervals():
    record(sid="s", kind="k", event={}, ts=0.0)
    record(sid="s", kind="k", event={}, ts=100.0)

    slept = []

    async def fake_sleep(d):
        slept.append(d)

    async def drive():
        return [f async for f in replay_stream(speed=100.0, _sleep=fake_sleep)]

    _run_async(drive())
    assert slept == [pytest.approx(1.0)]


def test_replay_negative_speed_raises():
    async def drive():
        async for _ in replay_stream(speed=-1.0):
            pass

    with pytest.raises(ValueError):
        _run_async(drive())
