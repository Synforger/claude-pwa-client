"""JSONL 行から推論を止める要因を検出して Web Push を飛ばす。

旧 SDK 経路の make_permission_handler / _on_result_msg に相当する役割を、 PTY/JSONL 経路で
再現する場所。 `monitor_all_sessions_loop` が全 session を tail して各行を渡すので、
PWA 接続有無に関係なく通知発火する (= SSE 経路 `_lines_to_sse` からは呼ばない、 二重発火回避)。

検出対象:
- AskUserQuestion (assistant 行の tool_use)
- 異常 stop_reason (max_tokens / refusal / pause_turn / model_context_window_exceeded)
- Agent / Workflow の task-notification (= バックグラウンド子エージェントの完了・失敗。
  Monitor event / 背景 Bash は高頻度でうるさいため対象外、 2026-07-27 audit §1-3 で確定)

正常 stop_reason (end_turn / tool_use) は除外 (= turn 完了通知は Stop hook 経路で別途)。
"""
from __future__ import annotations

import asyncio
import re
import time

from backend.core.jsonl_tail import parse_jsonl_timestamp
from backend.core.push import broadcast_push, notification_title_for
from backend.jsonl.events import parse_task_notification


# 推論が止まる原因として通知すべき stop_reason → ユーザ向けラベル。 旧 SDK 経路で
# StopReasonChip として MessageItem に表示してたのと同じ集合 + tool_use は除外
# (= turn 継続中なので止まりではない)。
_STOP_REASON_NOTIF_LABELS = {
    "max_tokens": "⚠ トークン上限で停止",
    "refusal": "🚫 拒否されました",
    "pause_turn": "⏸ 一時停止",
    "model_context_window_exceeded": "⚠ コンテキスト窓超過",
}

# JSONL 行の `timestamp` (ISO 8601) が現在時刻から N 秒以内なら「新着 tail」 とみなす。
# 初回 replay (= 500 行) で過去行を読み返した時に古い AskUserQuestion / stop_reason
# 異常を再通知しないための gate。
_PUSH_FRESH_WINDOW_SEC = 60.0


def is_fresh_line(line: dict) -> bool:
    """line の timestamp が直近 _PUSH_FRESH_WINDOW_SEC 内ならば True。"""
    line_time = parse_jsonl_timestamp(line.get("timestamp"))
    if line_time is None:
        return False
    return (time.time() - line_time) < _PUSH_FRESH_WINDOW_SEC


# Agent / Workflow の完了系 summary だけ push 対象にする (= harness 文言 prefix、
# frontend classifyTaskNotification と同族の判定)。 Monitor / Background command は除外。
_AGENT_NOTIF_RE = re.compile(r'^(?:Agent|Workflow) [\\]?"')


def _maybe_push_agent_completion(session_id: str, line: dict) -> bool:
    """user / queue-operation 行の task-notification が Agent / Workflow 完了なら push。"""
    if line.get("isSidechain") or line.get("isMeta"):
        return False
    text = None
    if line.get("type") == "user":
        content = (line.get("message") or {}).get("content")
        if isinstance(content, str):
            text = content
    elif line.get("type") == "queue-operation" and line.get("operation") == "enqueue":
        content = line.get("content")
        if isinstance(content, str):
            text = content
    if not text:
        return False
    task = parse_task_notification(text)
    if task is None:
        return False
    summary = task.get("summary") or ""
    if not _AGENT_NOTIF_RE.match(summary):
        return False
    if not is_fresh_line(line):
        return False
    title = notification_title_for(session_id)
    asyncio.create_task(broadcast_push(f"🤖 {summary}", title, session_id))
    return True


def maybe_push_blockers(session_id: str, line: dict) -> None:
    """AskUserQuestion 発火 / stop_reason 異常 / Agent 完了を検出して push を発火する。

    初回 replay で過去行が再流入した時の再通知を防ぐため、 `is_fresh_line` で
    タイムスタンプが直近 60 秒以内の行のみ push 発火する。
    """
    if _maybe_push_agent_completion(session_id, line):
        return
    if line.get("type") != "assistant" or line.get("isSidechain") or line.get("isMeta"):
        return
    if not is_fresh_line(line):
        return
    msg = line.get("message") or {}

    # AskUserQuestion 発火
    content = msg.get("content")
    if isinstance(content, list):
        for block in content:
            if not isinstance(block, dict) or block.get("type") != "tool_use":
                continue
            if block.get("name") != "AskUserQuestion":
                continue
            inp = block.get("input") or {}
            questions = inp.get("questions") or []
            first_q = questions[0] if isinstance(questions, list) and questions else {}
            question_text = (
                first_q.get("question") if isinstance(first_q, dict) else None
            )
            if question_text:
                title = notification_title_for(session_id)
                asyncio.create_task(
                    broadcast_push(f"❓ {question_text}", title, session_id)
                )
                return  # 1 行から複数 push を発火させない

    # stop_reason 異常系
    stop_reason = msg.get("stop_reason")
    label = _STOP_REASON_NOTIF_LABELS.get(stop_reason)
    if label:
        title = notification_title_for(session_id)
        asyncio.create_task(broadcast_push(label, title, session_id))
