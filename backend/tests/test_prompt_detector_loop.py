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
            # 初回 tick: seed のみ、 publish しない (= backend restart 直後の push
            # 一斉発火を抑える hotfix)
            tail_holder["value"] = ""
            await loop_mod._tick_one(sid)
            assert await _drain(q) == []
            assert loop_mod._detector_states[sid].seeded is True

            # 2 tick 目以降: 選択肢 dialog → INLINE_TUI 遷移で 1 発 publish
            tail_holder["value"] = "❯ 1. Yes, allow all\n  2. No, exit\n─────"
            await loop_mod._tick_one(sid)
            events = await _drain(q)
            assert len(events) == 1
            e = events[0]
            assert e["type"] == "prompt_state"
            assert e["sid"] == sid
            assert e["state"] == PromptState.INLINE_TUI.value
            assert "1. Yes, allow all" in e["excerpt"]
        finally:
            jsonl_event_broadcaster.unsubscribe(sid, q)

    _run(run())


def test_first_tick_is_seed_only_even_if_state_is_waiting(stub_session):
    """hotfix: backend restart 時、 既に INLINE_TUI 状態でも初回 tick は seed 扱い
    (= 「backend が起きた瞬間に session が waiting だった」 だけで push しない)。"""
    sid, tail_holder, alt_holder, push_calls = stub_session

    async def run():
        q = jsonl_event_broadcaster.subscribe(sid)
        try:
            tail_holder["value"] = "❯ 1. Yes\n  2. No"
            await loop_mod._tick_one(sid)
            assert await _drain(q) == []
            assert len(push_calls) == 0
            state = loop_mod._detector_states[sid]
            assert state.seeded is True
            assert state.current_state == PromptState.INLINE_TUI
        finally:
            jsonl_event_broadcaster.unsubscribe(sid, q)

    _run(run())


def test_tick_no_publish_on_repeated_same_state(stub_session):
    sid, tail_holder, alt_holder, _ = stub_session

    async def run():
        q = jsonl_event_broadcaster.subscribe(sid)
        try:
            # 1 tick 目: seed のみ (= INLINE_TUI に固定)
            tail_holder["value"] = "❯ 1. Yes\n  2. No\n─"
            await loop_mod._tick_one(sid)
            assert await _drain(q) == []

            # 2 tick 目: 同 state 維持 → 追加 publish なし
            await loop_mod._tick_one(sid)
            second = await _drain(q)
            assert second == []
        finally:
            jsonl_event_broadcaster.unsubscribe(sid, q)

    _run(run())


def test_tick_publishes_on_excerpt_change_within_same_state(stub_session):
    """Phase 4b: arrow picker で ❯ が移動しただけ (= state=inline_tui 据え置き、
    excerpt のみ更新) の時、 SSE publish は走らせて chip の text を live 更新する。
    push は走らせない (= 遷移じゃないので通知連発しない)。"""
    sid, tail_holder, alt_holder, push_calls = stub_session

    async def run():
        q = jsonl_event_broadcaster.subscribe(sid)
        try:
            # 1 tick 目: seed
            tail_holder["value"] = "❯ 1. apple\n  2. banana"
            await loop_mod._tick_one(sid)
            await _drain(q)
            push_calls.clear()

            # 2 tick 目: excerpt 変化 (= ❯ が下に移動、 state は INLINE_TUI 継続)
            tail_holder["value"] = "  1. apple\n❯ 2. banana"
            await loop_mod._tick_one(sid)
            events = await _drain(q)
            assert len(events) == 1
            assert events[0]["state"] == "inline_tui"
            await asyncio.sleep(0.02)
            assert len(push_calls) == 0
        finally:
            jsonl_event_broadcaster.unsubscribe(sid, q)

    _run(run())


def test_push_fires_on_text_prompt_transition(stub_session):
    sid, tail_holder, alt_holder, push_calls = stub_session

    async def run():
        q = jsonl_event_broadcaster.subscribe(sid)
        try:
            # seed 用の 1 tick 目: 中立 tail (= ACTIVE 相当) で seed し、 tier C の
            # hit が「seed の一部」 として飲まれないようにする。
            tail_holder["value"] = "just some running output"
            await loop_mod._tick_one(sid)
            await _drain(q)

            # 2 tick 目に prompt が現れた体で: tail 差替 + idle 起点を過去へ
            tail_holder["value"] = "[sudo] password for alice: "
            await loop_mod._tick_one(sid)
            # tier C を確実に通すため hash 起点を過去にずらし grace も無効化
            state = loop_mod._detector_states[sid]
            state.hash_first_seen_at -= 3.0
            state.last_input_sent_at = 0.0
            await _drain(q)
            push_calls.clear()

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


def test_current_prompt_event_synthesizes_active_for_unknown_sid():
    """detector が値を持たない sid は active 合成 event (= stale banner の消灯用)。"""
    loop_mod._last_events.clear()
    ev = loop_mod.current_prompt_event("ses_unknown")
    assert ev["type"] == "prompt_state"
    assert ev["sid"] == "ses_unknown"
    assert ev["state"] == "active"
    assert ev["input_mode"] == "none"
    assert ev["options"] == []


def test_current_prompt_event_mirrors_seed_and_publish(stub_session):
    """seed tick (= publish なし) でも snapshot は現実を映し、 caller の変更が保持側を汚さない。"""
    sid, tail_holder, alt_holder, _ = stub_session
    loop_mod._last_events.clear()

    async def run():
        # seed tick: INLINE_TUI 状態で起動した体
        tail_holder["value"] = "❯ 1. Yes\n  2. No"
        await loop_mod._tick_one(sid)
        snap = loop_mod.current_prompt_event(sid)
        assert snap["state"] == "inline_tui"
        # caller 側の mutate (= envelope 注入相当) が保持側に漏れない
        snap["corr_id"] = "deadbeef"
        assert "corr_id" not in loop_mod._last_events[sid]

        # 通常入力に戻る遷移 → snapshot も追従
        tail_holder["value"] = "just some running output"
        await loop_mod._tick_one(sid)
        assert loop_mod.current_prompt_event(sid)["state"] != "inline_tui"

    _run(run())
    loop_mod._last_events.clear()


def test_tick_cleans_last_event_when_session_gone(monkeypatch, stub_session):
    """session 消滅時は snapshot も掃除 (= 次接続では active 合成に倒れる)。"""
    sid, tail_holder, alt_holder, _ = stub_session

    async def run():
        tail_holder["value"] = "hello"
        await loop_mod._tick_one(sid)
        assert sid in loop_mod._last_events
        monkeypatch.setattr(loop_mod, "has_tmux_session", lambda s: False)
        await loop_mod._tick_one(sid)
        assert sid not in loop_mod._last_events

    _run(run())


def test_poll_interval_stretches_only_for_idle():
    """適応 poll: IDLE 継続中だけ間隔が伸びる (= それ以外は 500ms 維持)。"""
    from backend.terminal.prompt_detector import DetectorState, PromptState

    assert loop_mod._poll_interval_for(None) == loop_mod.POLL_INTERVAL_SEC
    s = DetectorState()
    s.current_state = PromptState.ACTIVE
    assert loop_mod._poll_interval_for(s) == loop_mod.POLL_INTERVAL_SEC
    s.current_state = PromptState.INLINE_TUI
    assert loop_mod._poll_interval_for(s) == loop_mod.POLL_INTERVAL_SEC
    s.current_state = PromptState.IDLE
    assert loop_mod._poll_interval_for(s) == loop_mod.IDLE_POLL_INTERVAL_SEC


def test_note_user_input_resets_adaptive_poll(stub_session):
    """ユーザ入力で IDLE の遅い poll が即 fast に戻る (= _next_poll_at が消える)。"""
    sid, *_ = stub_session

    async def run():
        loop_mod._next_poll_at[sid] = 10_000_000.0  # 遠い未来 (= skip 中の体)
        loop_mod.note_user_input(sid)
        assert sid not in loop_mod._next_poll_at

    _run(run())
    loop_mod._next_poll_at.clear()
