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


# --- 2026-07-27 audit 充填: 「新 type 追加のたび 1 ケース」 宣言に全 type を追随 ---


def test_user_tool_result_emits_user_event():
    """tool_result を含む user 行 → `user` event (= tool_use への結果紐付け専用)"""
    line = {
        "type": "user", "uuid": "u-tool-1",
        "message": {"content": [{"type": "tool_result", "tool_use_id": "t1", "content": "ok"}]},
    }
    ev = _find_event(jsonl_line_to_events(line), "user")
    assert ev is not None
    assert ev["message"]["content"][0]["type"] == "tool_result"


def test_mode_line_emits_mode_event():
    ev = _find_event(jsonl_line_to_events({"type": "mode", "mode": "plan"}), "mode")
    assert ev is not None and ev["mode"] == "plan"


def test_permission_mode_line_emits_permission_mode_event():
    line = {"type": "permission-mode", "permissionMode": "acceptEdits"}
    ev = _find_event(jsonl_line_to_events(line), "permission_mode")
    assert ev is not None and ev["permissionMode"] == "acceptEdits"


def test_pr_link_line_emits_pr_link_event():
    line = {"type": "pr-link", "uuid": "pr-1", "prNumber": 42,
            "prUrl": "https://example.com/pr/42", "prRepository": "o/r", "timestamp": "t"}
    ev = _find_event(jsonl_line_to_events(line), "pr_link")
    assert ev is not None and ev["prNumber"] == 42 and ev["prUrl"].endswith("/42")


def test_budget_attachment_emits_budget_event():
    line = {"type": "attachment", "uuid": "b-1",
            "attachment": {"type": "budget_usd", "used": 1.5, "total": 10.0, "remaining": 8.5}}
    ev = _find_event(jsonl_line_to_events(line), "budget")
    assert ev is not None and ev["remaining"] == 8.5


def test_hook_error_attachment_emits_hook_error_event():
    line = {"type": "attachment", "uuid": "h-1", "timestamp": "t",
            "attachment": {"type": "hook_non_blocking_error", "hookName": "x",
                           "hookEvent": "PostToolUse", "exitCode": 1, "stderr": "boom"}}
    ev = _find_event(jsonl_line_to_events(line), "hook_error")
    assert ev is not None and ev["exitCode"] == 1 and ev["stderr"] == "boom"


def test_file_attachment_emits_attachment_event():
    line = {"type": "attachment", "uuid": "f-1",
            "attachment": {"type": "file", "path": "/x/y.png"}}
    ev = _find_event(jsonl_line_to_events(line), "attachment")
    assert ev is not None and ev["subtype"] == "file"


def test_task_notification_user_line_emits_task_notification_event():
    text = ("<task-notification>\n<task-id>b123</task-id>\n"
            "<summary>Background command \"x\" completed (exit code 0)</summary>\n"
            "</task-notification>")
    line = {"type": "user", "uuid": "tn-1", "message": {"content": text}}
    ev = _find_event(jsonl_line_to_events(line), "task_notification")
    assert ev is not None and ev["taskId"] == "b123" and ev["exitCode"] == 0


def test_compact_boundary_emits_system_event():
    line = {"type": "system", "subtype": "compact_boundary", "uuid": "c-1",
            "trigger": "auto", "preTokens": 100, "postTokens": 10, "durationMs": 5}
    ev = _find_event(jsonl_line_to_events(line), "system")
    assert ev is not None and ev["compactMetadata"]["trigger"] == "auto"


def test_api_error_emits_system_error_event():
    line = {"type": "system", "subtype": "api_error", "uuid": "e-1",
            "error": {"formatted": "overloaded", "status": 529}, "retryInMs": 1000}
    ev = _find_event(jsonl_line_to_events(line), "system_error")
    assert ev is not None and ev["status"] == 529 and ev["formatted"] == "overloaded"


def test_turn_duration_emits_turn_duration_event():
    line = {"type": "system", "subtype": "turn_duration", "uuid": "d-1",
            "parentUuid": "a-1", "durationMs": 1234, "messageCount": 3}
    ev = _find_event(jsonl_line_to_events(line), "turn_duration")
    assert ev is not None and ev["durationMs"] == 1234 and ev["parentUuid"] == "a-1"


def test_local_command_emits_system_note_event():
    line = {"type": "system", "subtype": "local_command", "uuid": "n-1", "content": "/model opus"}
    ev = _find_event(jsonl_line_to_events(line), "system_note")
    assert ev is not None and ev["subtype"] == "local_command" and "/model" in ev["content"]


def test_scheduled_task_fire_emits_system_note_event():
    line = {"type": "system", "subtype": "scheduled_task_fire", "uuid": "n-2", "content": "loop"}
    ev = _find_event(jsonl_line_to_events(line), "system_note")
    assert ev is not None and ev["subtype"] == "scheduled_task_fire"


def test_ask_user_question_tool_use_emits_dedicated_event():
    line = {"type": "assistant", "uuid": "q-1",
            "message": {"content": [{"type": "tool_use", "id": "tq", "name": "AskUserQuestion",
                                     "input": {"questions": [{"question": "A or B?"}]}}]}}
    ev = _find_event(jsonl_line_to_events(line), "ask_user_question")
    assert ev is not None and ev["tool_use_id"] == "tq"
    assert ev["input"]["questions"][0]["question"] == "A or B?"
