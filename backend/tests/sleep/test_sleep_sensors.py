"""What the sleep sensors read (`sleep/sleep_sensors.py`): the record, its sub-agents' records, the process tree, and the
order in which the facts of a tab are read."""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

from datetime import datetime, timezone

import pytest

from backend.sleep import sleep_judgement as j
from backend.sleep import sleep_sensors as sensors
from backend.sleep.record_facts import RecordFacts


def _line(row: dict) -> bytes:
    return json.dumps(row).encode() + b"\n"


PROMPT = {"type": "user", "message": {"content": "go"}}
WAKEUP = {"type": "assistant", "message": {"content": [{"type": "tool_use", "id": "t", "name": "ScheduleWakeup"}]}}
RESULT = {"type": "user", "message": {"content": [{"type": "tool_result", "tool_use_id": "t", "content": "ok"}]}}
DONE = {"type": "assistant", "message": {"content": [{"type": "text", "text": "done"}]}}


@pytest.fixture(autouse=True)
def _fresh_scans():
    sensors._scans.clear()
    yield
    sensors._scans.clear()


def test_a_record_is_read_and_a_later_write_reads_only_the_new_rows(tmp_path):
    record = tmp_path / "c.jsonl"
    record.write_bytes(_line(PROMPT) + _line(WAKEUP) + _line(RESULT) + _line(DONE))
    assert sensors.record_facts_of(record).wakeup_pending is True
    offset = sensors._scans[str(record)][0]
    assert offset == record.stat().st_size
    with record.open("ab") as fh:
        fh.write(_line(PROMPT))
    assert sensors.record_facts_of(record).wakeup_pending is False
    assert sensors._scans[str(record)][0] == record.stat().st_size


def test_a_line_still_being_written_is_left_for_the_next_look(tmp_path):
    record = tmp_path / "c.jsonl"
    whole = _line(WAKEUP)
    record.write_bytes(_line(PROMPT) + whole[: len(whole) // 2])
    assert sensors.record_facts_of(record).wakeup_pending is False
    record.write_bytes(_line(PROMPT) + whole)
    assert sensors.record_facts_of(record).wakeup_pending is True


def test_a_record_is_read_in_pieces_without_losing_a_line_on_the_seams(tmp_path, monkeypatch):
    monkeypatch.setattr(sensors, "READ_CHUNK_BYTES", 7)
    record = tmp_path / "c.jsonl"
    rows = [PROMPT, WAKEUP, RESULT, DONE, PROMPT, WAKEUP]
    record.write_bytes(b"".join(_line(row) for row in rows))
    facts = sensors.record_facts_of(record)
    assert facts == RecordFacts(cron_open=0, wakeup_pending=True, awaiting_tool_result=True)
    assert sensors._scans[str(record)][0] == record.stat().st_size


def test_a_record_that_shrank_is_read_again_from_its_start(tmp_path):
    record = tmp_path / "c.jsonl"
    record.write_bytes(_line(PROMPT) + _line(WAKEUP) + _line(RESULT) + _line(DONE))
    assert sensors.record_facts_of(record).wakeup_pending is True
    record.write_bytes(_line(PROMPT))
    assert sensors.record_facts_of(record) == RecordFacts()


def test_a_line_that_is_not_json_is_skipped(tmp_path):
    record = tmp_path / "c.jsonl"
    record.write_bytes(b"{not json\n" + _line(WAKEUP))
    assert sensors.record_facts_of(record).wakeup_pending is True


def test_the_returned_facts_are_a_copy(tmp_path):
    record = tmp_path / "c.jsonl"
    record.write_bytes(_line(WAKEUP))
    sensors.record_facts_of(record).wakeup_pending = False
    assert sensors.record_facts_of(record).wakeup_pending is True


# --- when the conversation last did anything ---


def _stamped(row: dict, at: float) -> dict:
    """`row` with the ISO time Claude Code writes on it."""
    return {**row, "timestamp": datetime.fromtimestamp(at, tz=timezone.utc).isoformat().replace("+00:00", "Z")}


def _activity(record: Path) -> float:
    return sensors.last_activity(record, sensors.record_facts_of(record))


def test_activity_is_the_newest_row_time_not_the_file_s_modification_time(tmp_path):
    # a running claude rewrites its record without adding a row: the file is new, the conversation is not
    record = tmp_path / "c.jsonl"
    record.write_bytes(_line(_stamped(PROMPT, 1000)) + _line(_stamped(DONE, 2000)))
    os.utime(record, (9000, 9000))
    assert _activity(record) == 2000


def test_activity_counts_the_rows_of_the_sub_agents(tmp_path):
    record = tmp_path / "c.jsonl"
    record.write_bytes(_line(_stamped(PROMPT, 1000)))
    sub = tmp_path / "c" / "subagents"
    sub.mkdir(parents=True)
    (sub / "agent-1.jsonl").write_bytes(_line({**_stamped(DONE, 5000), "isSidechain": True}))
    os.utime(sub / "agent-1.jsonl", (100, 100))
    assert _activity(record) == 5000


def test_an_old_sub_agent_record_does_not_make_the_record_look_newer(tmp_path):
    record = tmp_path / "c.jsonl"
    record.write_bytes(_line(_stamped(DONE, 9000)))
    (tmp_path / "c" / "subagents").mkdir(parents=True)
    (tmp_path / "c" / "subagents" / "agent-1.jsonl").write_bytes(_line(_stamped(DONE, 100)))
    assert _activity(record) == 9000


def test_a_record_without_row_times_counts_by_its_modification_time(tmp_path):
    record = tmp_path / "c.jsonl"
    record.write_bytes(_line(PROMPT))
    os.utime(record, (1234, 1234))
    assert _activity(record) == 1234


def test_a_tab_whose_record_was_only_rewritten_is_quiet(monkeypatch, tmp_path):
    _stand_in(monkeypatch, tmp_path)
    record = tmp_path / "c.jsonl"                         # the record the stand-in answers with
    two_hours_ago = time.time() - 7200
    record.write_bytes(_line(_stamped(PROMPT, two_hours_ago)) + _line(_stamped(DONE, two_hours_ago)))
    os.utime(record, None)                                # rewritten just now, two hours after its last row
    facts = sensors.gather("ses_x", 60)
    assert facts.quiet_minutes > 100 and j.judge(facts, 60) == ()


# --- the processes under a claude ---


def test_the_process_tree_lists_what_runs_under_a_claude():
    child = subprocess.Popen(["sh", "-c", "sleep 30 & wait"])
    try:
        deadline = time.time() + 5
        names: tuple[str, ...] = ()
        while time.time() < deadline and "sleep" not in names:
            tree = sensors.process_tree(os.getpid())
            names = j.foreign_processes(tree)
            time.sleep(0.05)
        assert "sleep" in names
    finally:
        child.kill()
        child.wait()


def test_a_process_that_is_gone_has_no_tree():
    assert sensors.process_tree(2 ** 22 + 12345) == ()


def test_a_tool_started_by_node_is_known_by_its_arguments(tmp_path):
    script = tmp_path / "pyright-langserver"
    script.write_text("import time; time.sleep(30)\n")
    child = subprocess.Popen([sys.executable, str(script)])
    try:
        deadline = time.time() + 5
        while time.time() < deadline:
            tree = [node for node in sensors.process_tree(os.getpid()) if "pyright-langserver" in node.names]
            if tree:
                break
            time.sleep(0.05)
        assert tree and j.foreign_processes(tuple(tree)) == ()
    finally:
        child.kill()
        child.wait()


# --- the order of reading ---


def _stand_in(monkeypatch, tmp_path: Path, **over):
    """Everything `gather` reads, replaced; `over` changes single answers."""
    record = tmp_path / "c.jsonl"
    record.write_bytes(_line(PROMPT) + _line(DONE))
    os.utime(record, (time.time() - 7200, time.time() - 7200))
    calls: list[str] = []
    answers = {
        "pid": 4242, "ready": True, "busy": False, "queued": 0, "call": False, "pct": 10, "asked": False,
        "tree": (), "record": record, **over,
    }

    def note(name, value):
        def read(*_args):
            calls.append(name)
            return value
        return read

    monkeypatch.setattr(sensors, "claude_pid_in_pane", note("pid", answers["pid"]))
    monkeypatch.setattr(sensors.input_ready, "is_ready", note("ready", answers["ready"]))
    monkeypatch.setattr(sensors, "is_busy", note("busy", answers["busy"]))
    monkeypatch.setattr(sensors, "is_session_on_call", note("call", answers["call"]))
    monkeypatch.setattr(sensors.jsonl_watcher, "get_jsonl_for", note("record", answers["record"]))
    monkeypatch.setattr(sensors, "context_pct_of", note("pct", answers["pct"]))
    monkeypatch.setattr(sensors.rollover, "asked", note("asked", answers["asked"]))
    monkeypatch.setattr(sensors, "process_tree", note("tree", answers["tree"]))
    monkeypatch.setattr(sensors, "rollover_idle_pct", lambda _sid: 40)
    sensors.stream_states.pop("ses_x", None)
    return calls


def test_a_tab_that_may_sleep_has_all_its_facts_read(monkeypatch, tmp_path):
    calls = _stand_in(monkeypatch, tmp_path)
    facts = sensors.gather("ses_x", 60)
    assert j.judge(facts, 60) == ()
    assert facts.foreign_processes == () and facts.record == RecordFacts() and facts.quiet_minutes > 100
    assert calls[-1] == "tree"


def test_a_tab_without_a_claude_costs_one_process_lookup(monkeypatch, tmp_path):
    calls = _stand_in(monkeypatch, tmp_path, pid=None)
    assert sensors.gather("ses_x", 60) == j.SleepFacts(claude_running=False)
    assert calls == ["pid"]


def test_a_tab_that_is_answering_is_not_read_further(monkeypatch, tmp_path):
    calls = _stand_in(monkeypatch, tmp_path, busy=True)
    facts = sensors.gather("ses_x", 60)
    assert j.judge(facts, 60) == (j.TURN_OPEN,)
    assert "record" not in calls and "tree" not in calls


def test_a_tab_with_a_message_queued_behind_its_turn_is_open(monkeypatch, tmp_path):
    from backend._common.state import StreamState  # noqa: PLC0415
    _stand_in(monkeypatch, tmp_path)
    sensors.stream_states["ses_x"] = StreamState(queued_sends=1)
    try:
        assert j.judge(sensors.gather("ses_x", 60), 60) == (j.TURN_OPEN,)
    finally:
        sensors.stream_states.pop("ses_x", None)


def test_a_tab_that_is_not_quiet_is_not_read_for_processes(monkeypatch, tmp_path):
    calls = _stand_in(monkeypatch, tmp_path)
    facts = sensors.gather("ses_x", 60 * 24)
    assert j.judge(facts, 60 * 24) == (j.NOT_QUIET,)
    assert "tree" not in calls and "pct" not in calls


def test_a_tab_with_a_command_running_is_left_awake(monkeypatch, tmp_path):
    _stand_in(monkeypatch, tmp_path, tree=(j.ProcessNode(names=("python3",)),))
    assert j.judge(sensors.gather("ses_x", 60), 60) == (j.PROCESSES_RUNNING,)


def test_a_tab_without_a_record_is_left_awake(monkeypatch, tmp_path):
    _stand_in(monkeypatch, tmp_path, record=None)
    assert j.judge(sensors.gather("ses_x", 60), 60) == (j.NO_RECORD,)


def test_a_tab_whose_rollover_was_asked_is_left_awake(monkeypatch, tmp_path):
    _stand_in(monkeypatch, tmp_path, asked=True)
    assert j.judge(sensors.gather("ses_x", 60), 60) == (j.ROLLING_OVER,)


def test_a_tab_still_starting_is_left_awake(monkeypatch, tmp_path):
    _stand_in(monkeypatch, tmp_path, ready=False)
    assert j.judge(sensors.gather("ses_x", 60), 60) == (j.STARTING,)


def test_a_tab_a_limit_stopped_is_read_past_its_open_turn_to_the_processes_under_it(monkeypatch, tmp_path):
    calls = _stand_in(monkeypatch, tmp_path, busy=True, ready=False, tree=(j.ProcessNode(names=("sleep",)),))
    facts = sensors.gather("ses_x", 0, by_hand=True, stopped_by_limit=True)
    assert "record" in calls and calls[-1] == "tree"
    assert j.judge(facts, 0, by_hand=True, stopped_by_limit=True) == (j.PROCESSES_RUNNING,)
    # asked without the stop, the same tab is not read further than its open turn
    calls.clear()
    assert j.judge(sensors.gather("ses_x", 0, by_hand=True), 0, by_hand=True) == (j.STARTING, j.TURN_OPEN)
    assert "tree" not in calls


def test_a_tab_that_just_woke_is_quiet_from_zero_though_its_rows_are_old(monkeypatch, tmp_path):
    _stand_in(monkeypatch, tmp_path)
    sensors._woken_at.pop("ses_x", None)
    assert sensors.gather("ses_x", 60).quiet_minutes > 100                  # the record is two hours old
    sensors.note_woken("ses_x")
    try:
        assert sensors.gather("ses_x", 60).quiet_minutes < 1
        sensors.note_woken("ses_x", time.time() - 600)
        assert 9 < sensors.gather("ses_x", 60).quiet_minutes < 11          # measured from the time it woke
    finally:
        sensors._woken_at.pop("ses_x", None)


def test_a_row_newer_than_the_wake_is_what_the_quiet_time_is_measured_from(monkeypatch, tmp_path):
    _stand_in(monkeypatch, tmp_path)
    sensors.note_woken("ses_x", time.time() - 7 * 3600)                     # woke long ago: the rows are newer
    try:
        assert 100 < sensors.gather("ses_x", 60).quiet_minutes < 130
    finally:
        sensors._woken_at.pop("ses_x", None)
