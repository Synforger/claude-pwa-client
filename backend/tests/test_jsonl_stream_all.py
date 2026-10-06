"""`/jsonl/stream/all` endpoint と関連 helper の unit test (= F-15)。

- _parse_all_from: query string `sid:off,sid:off` → dict[sid, offset]
- _lines_to_events: JSONL 文字列 list → event dict list (= broadcaster publish 用)
- _process_new_lines: monitor 経路で broadcaster へ publish するか
"""
import asyncio
import json

import backend.jsonl.routes as jr
from backend.core.jsonl_predicates import AGENT_MESSAGE_OPENINGS
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
            jr._process_new_lines(sid, [(raw, 4321)])
            # 少なくとも 1 件は publish される (= assistant event)。 pos (= 行末 byte 位置)
            # が event とペアで届く (= SSE id 行が live 中も前進する土台)。
            ev, pos = await asyncio.wait_for(q.get(), timeout=0.1)
            assert ev.get("sid") == sid
            assert pos == 4321
        finally:
            state_mod.jsonl_event_broadcaster.unsubscribe(sid, q)

    _run(run())


def _published(state, sid, rows):
    """rows を monitor 経路へ通し、 publish された user_message を順に返す。"""
    state.stream_states[sid] = state_mod.StreamState(agent_id="a")
    state.agent_status[sid] = state_mod._make_agent_status("a")

    async def run():
        q = state_mod.jsonl_event_broadcaster.subscribe(sid)
        try:
            jr._process_new_lines(sid, [(json.dumps(row), 100 + i) for i, row in enumerate(rows)])
            out = []
            while not q.empty():
                ev, _pos = q.get_nowait()
                if ev.get("type") == "user_message":
                    out.append(ev)
            return out
        finally:
            state_mod.jsonl_event_broadcaster.unsubscribe(sid, q)

    return _run(run())


def _relayed(opening):
    return f'{opening}\n<agent-message from="tools" session="ses_x">\nhello\n</agent-message>'


def _queued(prompt, uuid):
    return {"type": "attachment", "uuid": uuid, "attachment": {
        "type": "queued_command", "prompt": prompt, "commandMode": "prompt", "origin": {"kind": "human"}}}


def test_a_message_from_another_tab_does_not_take_the_send_id_the_operator_s_words_wait_for(isolated_state):
    """画面が送った発話は send_id で楽観 bubble と結び付く。 連絡は画面が送った物ではないので、 先に記録へ
    載っても、 人の送信が待っている send_id を取らない (= 作業中に届いた連絡も、 手空きで届いた連絡も)。"""
    for n, opening in enumerate(AGENT_MESSAGE_OPENINGS):
        sid = f"ses_bind{n}"
        jr.send_dedup.reset()
        assert jr.send_dedup.check_and_mark(sid, "S-typed") is False
        relayed_while_working, relayed_while_idle, typed = _published(isolated_state, sid, [
            _queued(f'<pasted_content id="4a58">\n{_relayed(opening)}\n</pasted_content id="4a58">', "u-r1"),
            {"type": "user", "uuid": "u-r2", "origin": {"kind": "human"}, "message": {"content": _relayed(opening)}},
            _queued("and the footer too", "u-t"),
        ])
        assert "send_id" not in relayed_while_working and "send_id" not in relayed_while_idle
        assert typed["uuid"] == "u-t" and typed["send_id"] == "S-typed"
    jr.send_dedup.reset()
