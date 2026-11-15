"""The working child of a parent tab that the tests of the child watch look at."""
from __future__ import annotations

import json
import time
from types import SimpleNamespace

import pytest

import backend.child_watch.watch_patrol as patrol
import backend.child_watch.watch_sensors as sensors
from backend._common.state import register_session
from backend.account_fallback.fallback_sensors import TabBreak
from backend.sleep.sleep_sensors import record_facts_of
from backend.tests.child_watch.samples import answer_row
from backend.tests.limit_samples import iso, message_row


@pytest.fixture
def env(tmp_path, monkeypatch, isolated_state, agent_folder):
    """A working child of a parent tab whose conversation ends in an answer 10 minutes ago, with its claude at a break."""
    parent = register_session("agent_a", title="Parent")
    child = register_session("agent_a", title="Build the parser", child=True, parent_id=parent.id)
    now = time.time()
    record = tmp_path / "child.jsonl"
    record.write_text(json.dumps(message_row("u1", None, "user", "go", iso(now - 700))) + "\n"
                      + json.dumps(answer_row("a1", "u1", now - 600)) + "\n")
    memo = agent_folder / "pages" / child.id / "memo.md"
    memo.parent.mkdir(parents=True)
    memo.write_text(f"# {child.title}\n\n- 親のタブ: {parent.id}\n- 状態: 作業中\n", encoding="utf-8")
    env = SimpleNamespace(parent=parent, child=child, record=record, memo=memo, now=now, blocked_by=(), sent=[],
                          deliver=True)
    monkeypatch.setattr(sensors.jsonl_watcher, "get_jsonl_for", lambda _sid: record)

    def _break(_sid):
        facts = record_facts_of(record)
        return TabBreak(facts.limit_stop, env.blocked_by, owed=facts.continuation_owed)
    monkeypatch.setattr(sensors, "read_tab_break", _break)

    async def _send(session_id, text):
        env.sent.append((session_id, text))
        return env.deliver
    monkeypatch.setattr(patrol, "send_to_tab", _send)
    monkeypatch.setattr(patrol, "_seen_at_break", {})
    return env
