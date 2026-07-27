"""Agent / Workflow 完了 task-notification の push 発火 (= 2026-07-27 audit §1-3)。

確定方針: Agent / Workflow の完了・失敗だけ push、 Monitor event / 背景 Bash は
高頻度でうるさいため対象外。 見ている session への抑制は broadcast_push 側の既存機構。
"""
from __future__ import annotations

import datetime

import backend.jsonl.notifications as notif


def _fresh_ts() -> str:
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")


def _tn_line(summary: str, line_type: str = "user", fresh: bool = True) -> dict:
    text = (f"<task-notification>\n<task-id>t1</task-id>\n"
            f"<summary>{summary}</summary>\n</task-notification>")
    ts = _fresh_ts() if fresh else "2020-01-01T00:00:00.000Z"
    if line_type == "queue-operation":
        return {"type": "queue-operation", "operation": "enqueue", "content": text, "timestamp": ts}
    return {"type": "user", "message": {"content": text}, "timestamp": ts}


def _capture(monkeypatch):
    sent: list[tuple] = []

    async def fake_push(message, title=None, session_id=None):
        sent.append((message, session_id))

    def drive(coro):
        # 本番は monitor loop 内で create_task される。 テストは loop 無しで即駆動する。
        try:
            coro.send(None)
        except StopIteration:
            pass

    monkeypatch.setattr(notif, "broadcast_push", fake_push)
    monkeypatch.setattr(notif.asyncio, "create_task", drive)
    return sent


def test_agent_finished_triggers_push(monkeypatch):
    sent = _capture(monkeypatch)
    notif.maybe_push_blockers("ses_x", _tn_line('Agent \\"probe task\\" finished'))
    assert len(sent) == 1
    assert "probe task" in sent[0][0] and sent[0][1] == "ses_x"


def test_workflow_and_failed_variants_trigger_push(monkeypatch):
    sent = _capture(monkeypatch)
    notif.maybe_push_blockers("ses_x", _tn_line('Agent \\"x\\" failed: API error'))
    notif.maybe_push_blockers("ses_x", _tn_line('Workflow \\"review\\" finished', "queue-operation"))
    assert len(sent) == 2


def test_monitor_and_bash_notifications_do_not_push(monkeypatch):
    sent = _capture(monkeypatch)
    notif.maybe_push_blockers("ses_x", _tn_line('Monitor event: \\"tick\\"'))
    notif.maybe_push_blockers("ses_x", _tn_line('Monitor \\"tick\\" stream ended'))
    notif.maybe_push_blockers("ses_x", _tn_line('Background command \\"build\\" completed (exit code 0)'))
    assert sent == []


def test_stale_replay_lines_do_not_push(monkeypatch):
    sent = _capture(monkeypatch)
    notif.maybe_push_blockers("ses_x", _tn_line('Agent \\"old\\" finished', fresh=False))
    assert sent == []


def test_sidechain_lines_do_not_push(monkeypatch):
    sent = _capture(monkeypatch)
    line = _tn_line('Agent \\"nested\\" finished')
    line["isSidechain"] = True
    notif.maybe_push_blockers("ses_x", line)
    assert sent == []
