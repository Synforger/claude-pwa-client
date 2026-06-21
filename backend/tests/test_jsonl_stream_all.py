"""`/jsonl/stream/all` endpoint と関連 helper の unit test (= F-15)。

- _parse_all_from: query string `sid:off,sid:off` → dict[sid, offset]
- _lines_to_events: JSONL 文字列 list → event dict list (= broadcaster publish 用)
- _process_new_lines: monitor 経路で broadcaster へ publish するか
- _lines_to_sse: replay 専用 pure (= mutator を呼ばないこと、 F-06)
"""
import asyncio
import json

import backend.jsonl.routes as jr
import backend.state as state_mod


def _run(coro):
    """asyncio.run は default loop を閉じて後続 test を壊すので new loop を都度作る。"""
    loop = asyncio.new_event_loop()
    try:
        asyncio.set_event_loop(loop)
        return loop.run_until_complete(coro)
    finally:
        loop.close()
        asyncio.set_event_loop(asyncio.new_event_loop())


def test_parse_all_from_basic():
    assert jr._parse_all_from("sid_a:100,sid_b:200") == {"sid_a": 100, "sid_b": 200}


def test_parse_all_from_empty_and_none():
    assert jr._parse_all_from(None) == {}
    assert jr._parse_all_from("") == {}


def test_parse_all_from_skips_bad_entries():
    # bad: missing colon / bad int / empty sid
    assert jr._parse_all_from("sid_a:100,bogus,:55,sid_c:notanint,sid_d:300") == {
        "sid_a": 100,
        "sid_d": 300,
    }


def test_parse_all_from_handles_ses_prefix_with_colon():
    # sid 内に ':' は実際にはないが、 rpartition で末尾 ':' を offset 区切りとして扱う
    assert jr._parse_all_from("ses_abc:1234") == {"ses_abc": 1234}


def test_lines_to_events_emits_event_dicts():
    """assistant 1 行 + user 1 行 → event dict list (= jsonl_line_to_events と等価)。"""
    lines = [
        json.dumps({"type": "user", "uuid": "u1", "message": {"content": "go"}}),
        json.dumps({"type": "assistant", "uuid": "a1",
                    "message": {"content": [{"type": "text", "text": "hi"}]}}),
    ]
    evts = jr._lines_to_events(lines)
    types = [e.get("type") for e in evts]
    assert "user_message" in types
    assert "assistant" in types


def test_lines_to_events_skips_blank_and_bad_json():
    lines = ["", "  ", "not json", json.dumps({"type": "user", "message": {"content": "x"}})]
    evts = jr._lines_to_events(lines)
    assert any(e.get("type") == "user_message" for e in evts)


def test_lines_to_sse_no_mutate(isolated_state, monkeypatch):
    """F-06: 旧版は _lines_to_sse 内で _mutate_agent_status / _track_turn_start を呼び、
    monitor 経路と二重 driver で agent_status を mutate していた。 新版は replay 専用の
    pure 関数として降格 (= mutator は呼ばない)。 SSE 配信 frame だけが返る。"""
    state = isolated_state
    sid = "ses_pure"
    state.stream_states[sid] = state_mod.StreamState(agent_id="a")
    state.agent_status[sid] = state_mod._make_agent_status("a")
    # SSE replay 経路で「素ユーザ発話 + tool_use 付き assistant」 を流しても
    # agent_status は mutate されないことを確認 (= monitor 単一経路 invariant)。
    raw_user = json.dumps({"type": "user", "uuid": "u1", "message": {"content": "go"}})
    raw_asst = json.dumps({
        "type": "assistant", "uuid": "a1",
        "message": {"content": [
            {"type": "tool_use", "name": "TodoWrite", "id": "t1",
             "input": {"todos": [{"content": "x", "status": "pending", "activeForm": "x"}]}},
        ]},
    })
    before_todos = state.agent_status[sid].get("todos")
    frames = jr._lines_to_sse([raw_user, raw_asst], 100, sid)
    # frame は出る (= assistant event)
    assert len(frames) >= 1
    assert all(f.startswith("id: 100\ndata: ") for f in frames)
    # agent_status は mutate されていない (= 旧 dual-driver の race を排除)
    assert state.agent_status[sid].get("todos") == before_todos


def test_process_new_lines_publishes_to_broadcaster(isolated_state):
    """monitor 経路の _process_new_lines が JSONL 行から event を broadcaster へ publish する
    (= F-02 / F-06 の単一経路)。 publish された event には sid field が埋まる。"""
    state = isolated_state
    sid = "ses_pub"
    state.stream_states[sid] = state_mod.StreamState(agent_id="a")
    state.agent_status[sid] = state_mod._make_agent_status("a")

    async def run():
        q = state_mod.jsonl_event_broadcaster.subscribe(sid)
        try:
            raw = json.dumps({
                "type": "assistant", "uuid": "a1",
                "message": {"content": [{"type": "text", "text": "hi"}]},
            })
            jr._process_new_lines(sid, [raw])
            # 少なくとも 1 件は publish される (= assistant event)
            ev = await asyncio.wait_for(q.get(), timeout=0.1)
            assert ev.get("sid") == sid
        finally:
            state_mod.jsonl_event_broadcaster.unsubscribe(sid, q)

    _run(run())
