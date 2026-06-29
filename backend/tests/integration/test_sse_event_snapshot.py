"""SSE event shape の snapshot test (= scaffold).

JSONL 1 行 → `jsonl_line_to_events` → SSE wire payload の変換を、
代表的な input で固定化する。 backend/jsonl/events.py を refactor
(= 後続 wave で classify_jsonl_line 統合や mutate 経路 1 本化を
する時) しても、 既存 frontend が読める shape を維持してることを
回帰検知する。

scaffold としては最小 3 ケース (= assistant text / user message / result)
だけ入れて、 後続 wave で新 type / 新 field を足すたびにここに 1 ケース
追加する。 docs/internals/protocol/streams.md § event wire shape とミラー関係。

snapshot 戦略:
- 厳密一致でなく、 「必須 field の存在」 と「type」 「主要 payload」 を
  assert する。 backend 側で `uuid` だけ追加とか、 内部 implementation
  詳細 (= request_id 採番) は変わって OK。 仕様 (= docs に書いた shape)
  に対する drift を捉える。
"""
from backend.jsonl.events import jsonl_line_to_events


def _find_event(events: list[dict], event_type: str) -> dict | None:
    return next((e for e in events if e.get("type") == event_type), None)


def test_assistant_text_emits_assistant_event():
    """assistant 1 turn の JSONL 行 → `type: assistant` event を 1 つ emit"""
    line = {
        "type": "assistant",
        "uuid": "a-uuid-1",
        "message": {
            "content": [
                {"type": "text", "text": "Hello"},
            ],
        },
    }
    events = jsonl_line_to_events(line)

    assistant = _find_event(events, "assistant")
    assert assistant is not None
    assert assistant["uuid"] == "a-uuid-1"
    assert assistant["message"]["content"][0]["type"] == "text"
    assert assistant["message"]["content"][0]["text"] == "Hello"


def test_plain_user_text_emits_user_message_event():
    """素の user 発話 (= tool_result でない text-only) → `user_message` 正規化"""
    line = {
        "type": "user",
        "uuid": "u-uuid-1",
        "message": {"content": "Hello from user"},
    }
    events = jsonl_line_to_events(line)

    user_msg = _find_event(events, "user_message")
    assert user_msg is not None
    assert user_msg["text"] == "Hello from user"
    assert user_msg["uuid"] == "u-uuid-1"


def test_assistant_stop_reason_synthesises_result_event():
    """assistant 行に stop_reason が乗ったら `result` event を合成する.

    jsonl 上は `type: "result"` の独立行は無く、 assistant message の
    stop_reason ≠ tool_use から backend が合成する仕様。 frontend は
    `result` event を見て streaming flag を下ろし MetaLine を描画する.
    """
    line = {
        "type": "assistant",
        "uuid": "a-uuid-2",
        "message": {
            "content": [{"type": "text", "text": "done"}],
            "stop_reason": "end_turn",
            "usage": {"input_tokens": 10, "output_tokens": 5},
            "model": "claude-opus-4-8",
        },
    }
    events = jsonl_line_to_events(line)

    # assistant 本体 + result の 2 event 出る
    assistant = _find_event(events, "assistant")
    assert assistant is not None
    result = _find_event(events, "result")
    assert result is not None
    assert result["stop_reason"] == "end_turn"
    assert result.get("is_error") is False
    assert result["usage"]["input_tokens"] == 10
