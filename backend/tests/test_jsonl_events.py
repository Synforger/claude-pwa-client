"""jsonl_events.jsonl_line_to_events の単体テスト。

claude の JSONL 1 行が processStreamEvent.js の期待する event 形式に正しく
変換されることを、 行種別ごとに確認する。
"""
from backend.jsonl.events import jsonl_line_to_events, parse_task_notification


def test_assistant_tool_use_passthrough():
    line = {
        "type": "assistant",
        "uuid": "u1",
        "isSidechain": False,
        "message": {
            "role": "assistant",
            "content": [{"type": "tool_use", "id": "t1", "name": "Bash", "input": {"command": "ls"}}],
            "stop_reason": "tool_use",
        },
    }
    events = jsonl_line_to_events(line)
    assert len(events) == 1
    assert events[0]["type"] == "assistant"
    assert events[0]["uuid"] == "u1"
    assert events[0]["message"]["content"][0]["name"] == "Bash"


def test_assistant_text_end_turn_emits_result():
    line = {
        "type": "assistant",
        "uuid": "u2",
        "message": {
            "role": "assistant",
            "content": [{"type": "text", "text": "done"}],
            "stop_reason": "end_turn",
            "model": "claude-opus-4-7",
            "usage": {"input_tokens": 1, "output_tokens": 2},
        },
    }
    events = jsonl_line_to_events(line)
    types = [e["type"] for e in events]
    assert types == ["assistant", "result"]
    result = events[1]
    assert result["usage"] == {"input_tokens": 1, "output_tokens": 2}
    assert result["stop_reason"] == "end_turn"
    assert result["modelUsage"] == {"claude-opus-4-7": {}}


def test_assistant_thinking_tool_use_no_result():
    # stop_reason=tool_use (= turn 継続中) では result を合成しない
    line = {
        "type": "assistant",
        "uuid": "u3",
        "message": {
            "role": "assistant",
            "content": [{"type": "thinking", "thinking": "hmm"}],
            "stop_reason": "tool_use",
        },
    }
    events = jsonl_line_to_events(line)
    assert [e["type"] for e in events] == ["assistant"]


def test_ask_user_question_split():
    line = {
        "type": "assistant",
        "uuid": "u4",
        "message": {
            "role": "assistant",
            "content": [
                {"type": "tool_use", "id": "aq1", "name": "AskUserQuestion",
                 "input": {"questions": [{"question": "A or B?"}]}},
            ],
            "stop_reason": "tool_use",
        },
    }
    events = jsonl_line_to_events(line)
    types = [e["type"] for e in events]
    assert "assistant" in types
    assert "ask_user_question" in types
    aq = next(e for e in events if e["type"] == "ask_user_question")
    assert aq["tool_use_id"] == "aq1"
    assert aq["input"]["questions"][0]["question"] == "A or B?"


def test_user_tool_result():
    line = {
        "type": "user",
        "message": {
            "role": "user",
            "content": [{"type": "tool_result", "tool_use_id": "t1", "is_error": False, "content": "ok"}],
        },
        "toolUseResult": {"stdout": "ok"},
    }
    events = jsonl_line_to_events(line)
    assert len(events) == 1
    assert events[0]["type"] == "user"
    assert events[0]["message"]["content"][0]["tool_use_id"] == "t1"


def test_user_plain_prompt_string():
    line = {
        "type": "user",
        "uuid": "u5",
        "message": {"role": "user", "content": "ファイル一覧出して"},
    }
    events = jsonl_line_to_events(line)
    assert len(events) == 1
    assert events[0]["type"] == "user_message"
    assert events[0]["text"] == "ファイル一覧出して"
    assert events[0]["uuid"] == "u5"


def test_user_text_block_array_folds_to_user_message():
    line = {
        "type": "user",
        "uuid": "u6",
        "message": {"role": "user", "content": [{"type": "text", "text": "hello"}]},
    }
    events = jsonl_line_to_events(line)
    assert len(events) == 1
    assert events[0]["type"] == "user_message"
    assert events[0]["text"] == "hello"


def test_meta_message_skipped():
    # harness の malformed retry 注入 (isMeta:true) は chat に出さない
    line = {
        "type": "user",
        "isMeta": True,
        "message": {
            "role": "user",
            "content": "Your tool call was malformed and could not be parsed. Please retry.",
        },
    }
    assert jsonl_line_to_events(line) == []


def test_sidechain_skipped():
    line = {
        "type": "assistant",
        "uuid": "u7",
        "isSidechain": True,
        "message": {"role": "assistant", "content": [{"type": "text", "text": "subagent"}]},
    }
    assert jsonl_line_to_events(line) == []


def test_empty_user_string_skipped():
    line = {"type": "user", "message": {"role": "user", "content": "   "}}
    assert jsonl_line_to_events(line) == []


def test_unknown_type_skipped():
    # attachment / pr-link は今は専用 event を出す。 完全未知の type のみ skip 確認に絞る。
    assert jsonl_line_to_events({"type": "totally-unknown-type"}) == []
    assert jsonl_line_to_events("not a dict") == []


def test_slash_command_xml_skipped():
    # `/clear` 等の slash command を tmux 経由で送ると claude は
    # `<command-name>/clear</command-name>` 形式の user 行を JSONL に書く。
    # これはユーザ発話ではなく内部表現なので chat には出さない。
    line = {
        "type": "user",
        "uuid": "u-clear",
        "message": {
            "role": "user",
            "content": (
                "<command-name>/clear</command-name> "
                "<command-message>clear</command-message> "
                "<command-args></command-args>"
            ),
        },
    }
    assert jsonl_line_to_events(line) == []


def test_slash_command_xml_with_leading_whitespace_skipped():
    line = {
        "type": "user",
        "uuid": "u-model",
        "message": {
            "role": "user",
            "content": "  \n<command-name>/model</command-name> <command-message>model</command-message>",
        },
    }
    assert jsonl_line_to_events(line) == []


def test_local_command_stdout_skipped():
    # `/model sonnet` 実行後、 claude が応答を <local-command-stdout> XML で JSONL に書く。
    # これは harness の内部 stdout なので chat には出さない。
    line = {
        "type": "user",
        "uuid": "u-stdout",
        "message": {
            "role": "user",
            "content": (
                "<local-command-stdout>Set model to Sonnet 4.6 for this session"
                "</local-command-stdout>"
            ),
        },
    }
    assert jsonl_line_to_events(line) == []


def test_local_command_stderr_skipped():
    line = {
        "type": "user",
        "uuid": "u-stderr",
        "message": {
            "role": "user",
            "content": "<local-command-stderr>error</local-command-stderr>",
        },
    }
    assert jsonl_line_to_events(line) == []


_TASK_NOTE_TEXT = (
    "<task-notification>\n"
    "<task-id>b4aaezg2d</task-id>\n"
    "<tool-use-id>toolu_01L843</tool-use-id>\n"
    "<output-file>/private/tmp/claude-501/proj/sess/tasks/b4aaezg2d.output</output-file>\n"
    "<status>completed</status>\n"
    '<summary>Background command "unit tests" completed (exit code 0)</summary>\n'
    "</task-notification>"
)


def test_parse_task_notification_fields():
    # 意図: 各タグと summary 末尾の exit code が構造化 dict に抽出される
    t = parse_task_notification(_TASK_NOTE_TEXT)
    assert t == {
        "taskId": "b4aaezg2d",
        "toolUseId": "toolu_01L843",
        "outputFile": "/private/tmp/claude-501/proj/sess/tasks/b4aaezg2d.output",
        "status": "completed",
        "summary": 'Background command "unit tests" completed (exit code 0)',
        "exitCode": 0,
    }


def test_parse_task_notification_non_match():
    # 意図: task-notification でない文字列は None
    assert parse_task_notification("<command-name>/clear</command-name>") is None
    assert parse_task_notification("普通の発話") is None


def test_task_notification_emits_system_event_not_user():
    # 意図: harness の background task 完了通知は user_message ではなく
    # task_notification system event に変換される (= 右寄せ「自分が送った」 誤表示の解消)
    line = {
        "type": "user",
        "uuid": "u-task",
        "message": {"role": "user", "content": _TASK_NOTE_TEXT},
    }
    events = jsonl_line_to_events(line)
    assert len(events) == 1
    ev = events[0]
    assert ev["type"] == "task_notification"
    assert ev["uuid"] == "u-task"
    assert ev["status"] == "completed"
    assert ev["exitCode"] == 0
    assert ev["outputFile"].endswith("b4aaezg2d.output")


def test_task_notification_failure_exit_code():
    # 意図: exit code != 0 は exitCode に拾われる (= frontend の error 色判定用)
    text = _TASK_NOTE_TEXT.replace("exit code 0", "exit code 1")
    t = parse_task_notification(text)
    assert t["exitCode"] == 1


def test_compact_boundary_emits_event():
    # spec 推測: system 行は top-level に subtype + metadata 各 field を直接持つ
    # (= turn_duration が durationMs を top-level に持つのと同パターン)
    line = {
        "type": "system",
        "subtype": "compact_boundary",
        "uuid": "u-compact",
        "trigger": "auto",
        "preTokens": 180000,
        "postTokens": 45000,
        "durationMs": 1200,
        "timestamp": "2026-05-24T18:30:00.000Z",
    }
    events = jsonl_line_to_events(line)
    assert len(events) == 1
    ev = events[0]
    assert ev["type"] == "system"
    assert ev["subtype"] == "compact_boundary"
    assert ev["uuid"] == "u-compact"
    assert ev["compactMetadata"] == {
        "trigger": "auto",
        "preTokens": 180000,
        "postTokens": 45000,
        "durationMs": 1200,
    }


def test_compact_boundary_with_missing_metadata():
    # metadata 欠落でも banner だけ出せる (= 中身 None で frontend が安全に render)
    line = {"type": "system", "subtype": "compact_boundary", "uuid": "u-compact-min"}
    events = jsonl_line_to_events(line)
    assert len(events) == 1
    assert events[0]["compactMetadata"]["trigger"] is None


def test_other_system_subtypes_skipped():
    # 残り subtype (= stop_hook_summary / away_summary 等) は chat に出さない。
    # api_error / turn_duration は別途 system_error / turn_duration として表示する
    # (= 2026-06-12、 Fable 5 の jsonl で多発するためブラックボックス化を回避)。
    for sub in ("stop_hook_summary", "away_summary"):
        line = {"type": "system", "subtype": sub, "uuid": f"u-{sub}"}
        assert jsonl_line_to_events(line) == [], f"failed for subtype={sub}"


def test_system_api_error_emits_system_error_event():
    line = {
        "type": "system", "subtype": "api_error", "uuid": "u-err",
        "level": "error", "timestamp": "2026-06-11T16:46:00Z",
        "error": {
            "formatted": "529 Overloaded",
            "status": 529,
            "requestId": "req_abc",
            "isNetworkDown": False,
        },
        "retryInMs": 590, "retryAttempt": 2,
    }
    events = jsonl_line_to_events(line)
    assert len(events) == 1
    e = events[0]
    assert e["type"] == "system_error"
    assert e["formatted"] == "529 Overloaded"
    assert e["status"] == 529
    assert e["retryAttempt"] == 2


def test_system_turn_duration_emits_event():
    line = {
        "type": "system", "subtype": "turn_duration", "uuid": "u-td",
        "parentUuid": "p-1", "durationMs": 12345, "messageCount": 7,
        "timestamp": "2026-06-11T13:51:24.963Z",
    }
    events = jsonl_line_to_events(line)
    assert len(events) == 1
    assert events[0]["type"] == "turn_duration"
    assert events[0]["durationMs"] == 12345
    assert events[0]["parentUuid"] == "p-1"


def test_mode_and_permission_mode_events():
    assert jsonl_line_to_events({"type": "mode", "mode": "plan"}) == [
        {"type": "mode", "mode": "plan"}
    ]
    assert jsonl_line_to_events({"type": "permission-mode", "permissionMode": "bypassPermissions"}) == [
        {"type": "permission_mode", "permissionMode": "bypassPermissions"}
    ]


def test_attachment_queued_command_skipped():
    # 2026-06-12 棚卸し以降は内部メタとして chat 非表示。
    line = {
        "type": "attachment", "uuid": "u-att",
        "attachment": {"type": "queued_command", "content": "/clear"},
    }
    assert jsonl_line_to_events(line) == []


def test_attachment_deferred_tools_skipped():
    line = {
        "type": "attachment",
        "attachment": {"type": "deferred_tools_delta", "addedNames": ["WebFetch"]},
    }
    assert jsonl_line_to_events(line) == []


def test_pr_link_event():
    line = {
        "type": "pr-link", "uuid": "u-pr",
        "prNumber": 598, "prUrl": "https://github.com/org/repo/pull/598",
        "prRepository": "org/repo", "timestamp": "2026-06-06T07:21:29Z",
    }
    events = jsonl_line_to_events(line)
    assert len(events) == 1
    assert events[0]["type"] == "pr_link"
    assert events[0]["prNumber"] == 598
    assert events[0]["prUrl"].endswith("/598")


def test_hook_non_blocking_error_emits_event():
    line = {
        "type": "attachment", "uuid": "u-h",
        "attachment": {
            "type": "hook_non_blocking_error",
            "hookName": "SessionStart:startup", "hookEvent": "SessionStart",
            "exitCode": 7, "stderr": "boom", "command": "curl ...",
            "durationMs": 49,
        },
    }
    events = jsonl_line_to_events(line)
    assert len(events) == 1
    assert events[0]["type"] == "hook_error"
    assert events[0]["exitCode"] == 7
    assert events[0]["hookName"] == "SessionStart:startup"


def test_budget_usd_emits_budget_event():
    line = {
        "type": "attachment",
        "attachment": {"type": "budget_usd", "used": 1.5, "total": 10, "remaining": 8.5},
    }
    events = jsonl_line_to_events(line)
    assert events == [{"type": "budget", "used": 1.5, "total": 10, "remaining": 8.5}]


def test_attachment_file_emits_card():
    line = {"type": "attachment", "uuid": "u-file", "attachment": {"type": "file"}}
    events = jsonl_line_to_events(line)
    assert len(events) == 1
    assert events[0]["type"] == "attachment"
    assert events[0]["subtype"] == "file"


def test_attachment_internal_subtypes_skipped():
    # 2026-06-12 棚卸し: ユーザー手動添付 (file) と警告 (hook_non_blocking_error) /
    # 予算 (budget_usd) / 専用集約 (task_reminder) 以外はチャット非表示。
    for sub in (
        "edited_text_file", "skill_listing", "compact_file_reference",
        "command_permissions", "auto_mode", "queued_command",
        "deferred_tools_delta", "date_change",
    ):
        line = {"type": "attachment", "uuid": f"u-{sub}", "attachment": {"type": sub}}
        assert jsonl_line_to_events(line) == [], f"failed for {sub}"


def test_system_local_command_and_scheduled_emit_note():
    for sub in ("local_command", "scheduled_task_fire"):
        line = {"type": "system", "subtype": sub, "uuid": f"u-{sub}", "content": "x"}
        events = jsonl_line_to_events(line)
        assert len(events) == 1
        assert events[0]["type"] == "system_note"
        assert events[0]["subtype"] == sub


def test_queue_operation_with_task_notification():
    content = (
        "<task-notification><task-id>a1</task-id>"
        "<tool-use-id>tu_1</tool-use-id><status>completed</status>"
        "<summary>Agent done</summary></task-notification>"
    )
    line = {
        "type": "queue-operation", "operation": "enqueue",
        "timestamp": "2026-06-11T16:49:57Z", "content": content,
    }
    events = jsonl_line_to_events(line)
    assert len(events) == 1
    assert events[0]["type"] == "task_notification"
    assert events[0]["taskId"] == "a1"
    assert events[0]["status"] == "completed"
