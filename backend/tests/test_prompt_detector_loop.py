"""prompt_detector_loop の分岐 (= state 遷移 → SSE publish + Web Push) を verify。

tmux 依存 (has_tmux_session / get_pane_alternate_on / capture_pane_plain_tail) と
broadcast_push は monkeypatch で差し替え、 loop の意思決定だけを見る。

repo に pytest-asyncio が入ってないので、 test_jsonl_broadcaster と同じ _run helper
で async ケースを都度 run する。
"""
from __future__ import annotations

import asyncio

import pytest

from backend.state import jsonl_event_broadcaster
from backend.terminal import prompt_detector_loop as loop_mod
from backend.terminal.prompt_detector import PromptState


def _run(coro):
    loop = asyncio.new_event_loop()
    try:
        asyncio.set_event_loop(loop)
        return loop.run_until_complete(coro)
    finally:
        loop.close()
        asyncio.set_event_loop(asyncio.new_event_loop())


@pytest.fixture
def stub_session(monkeypatch):
    sid = "test-sid"
    tail_holder: dict[str, str] = {"value": ""}
    alt_holder: dict[str, bool] = {"value": False}
    push_calls: list[tuple[str, str, str]] = []

    monkeypatch.setattr(loop_mod, "sessions_meta", {sid: object()})
    monkeypatch.setattr(loop_mod, "has_tmux_session", lambda s: s == sid)
    monkeypatch.setattr(loop_mod, "get_pane_alternate_on", lambda s: alt_holder["value"])
    monkeypatch.setattr(loop_mod, "capture_pane_plain_tail", lambda s: tail_holder["value"])

    async def _fake_push(body: str, title: str, session_id: str):
        push_calls.append((title, body, session_id))
        return None

    monkeypatch.setattr(loop_mod, "broadcast_push", _fake_push)

    loop_mod._detector_states.clear()
    yield sid, tail_holder, alt_holder, push_calls
    loop_mod._detector_states.clear()


async def _drain(q: asyncio.Queue, timeout: float = 0.05) -> list[dict]:
    events: list[dict] = []
    try:
        while True:
            events.append(await asyncio.wait_for(q.get(), timeout=timeout))
    except asyncio.TimeoutError:
        return events


def test_tick_publishes_on_state_transition(stub_session):
    sid, tail_holder, alt_holder, push_calls = stub_session

    async def run():
        q = jsonl_event_broadcaster.subscribe(sid)
        try:
            # baseline: 空 tail → ACTIVE (初期 current_state == ACTIVE、 遷移なし)
            await loop_mod._tick_one(sid)
            assert await _drain(q) == []

            # 選択肢 dialog → INLINE_TUI 遷移で 1 発 publish
            tail_holder["value"] = "❯ 1. Yes, allow all\n  2. No, exit\n─────"
            await loop_mod._tick_one(sid)
            events = await _drain(q)
            assert len(events) == 1
            e = events[0]
            assert e["event"] == "prompt_state"
            assert e["sid"] == sid
            assert e["state"] == PromptState.INLINE_TUI.value
            assert "1. Yes, allow all" in e["excerpt"]
        finally:
            jsonl_event_broadcaster.unsubscribe(sid, q)

    _run(run())


def test_tick_no_publish_on_repeated_same_state(stub_session):
    sid, tail_holder, alt_holder, _ = stub_session

    async def run():
        q = jsonl_event_broadcaster.subscribe(sid)
        try:
            tail_holder["value"] = "❯ 1. Yes\n  2. No\n─"
            await loop_mod._tick_one(sid)
            first = await _drain(q)
            assert len(first) == 1

            await loop_mod._tick_one(sid)
            second = await _drain(q)
            assert second == []
        finally:
            jsonl_event_broadcaster.unsubscribe(sid, q)

    _run(run())


def test_push_fires_on_text_prompt_transition(stub_session):
    sid, tail_holder, alt_holder, push_calls = stub_session

    async def run():
        q = jsonl_event_broadcaster.subscribe(sid)
        try:
            # 1 度目: ACTIVE state に落ち着かせつつ hash を state に反映
            tail_holder["value"] = "[sudo] password for alice: "
            await loop_mod._tick_one(sid)
            await _drain(q)  # ここまでの emit を掃く

            # tier C を通す: hash 起点を 3s ずらす + grace 無効化
            state = loop_mod._detector_states[sid]
            state.hash_first_seen_at -= 3.0
            state.last_input_sent_at = 0.0

            await loop_mod._tick_one(sid)
            events = await _drain(q)
            assert len(events) == 1
            assert events[0]["state"] == PromptState.TEXT_PROMPT.value

            # push は fire-and-forget な asyncio.create_task なので余裕をもらう
            await asyncio.sleep(0.02)
            assert len(push_calls) == 1
            title, body, sid_arg = push_calls[0]
            assert "Waiting" in title
            assert "password for alice" in body
            assert sid_arg == sid
        finally:
            jsonl_event_broadcaster.unsubscribe(sid, q)

    _run(run())


def test_note_user_input_records_grace(stub_session):
    sid, *_ = stub_session

    async def run():
        loop_mod.note_user_input(sid)
        state = loop_mod._detector_states[sid]
        assert state.last_input_sent_at >= 0.0

    _run(run())


def test_tick_cleans_state_when_session_gone(monkeypatch, stub_session):
    sid, tail_holder, alt_holder, _ = stub_session

    async def run():
        tail_holder["value"] = "hello"
        await loop_mod._tick_one(sid)
        assert sid in loop_mod._detector_states

        monkeypatch.setattr(loop_mod, "has_tmux_session", lambda s: False)
        await loop_mod._tick_one(sid)
        assert sid not in loop_mod._detector_states

    _run(run())
