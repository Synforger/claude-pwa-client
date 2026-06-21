"""scan_subagent_tail の unit test (= backend-F-18)。

subagents/ の最新 agent-*.jsonl を末尾 1 パスで scan する共通基盤。 W1-D round 2-b で
routes/subagents.py の `_scan_agent_file` がこの API に切替わる想定。 latest_subagent_tool
は本基盤の薄い wrapper として動くことを担保。
"""
import json
import os

from backend.jsonl.session_status import (
    latest_subagent_tool,
    scan_subagent_tail,
)


def _write_agent_file(subdir, name, tool_calls, mtime=None):
    """tool_calls = [(name, id, input?)] を assistant tool_use 行として書く helper。"""
    subdir.mkdir(parents=True, exist_ok=True)
    p = subdir / name
    lines = []
    for spec in tool_calls:
        if len(spec) == 2:
            tname, tid = spec
            tinp = {}
        else:
            tname, tid, tinp = spec
        lines.append(json.dumps({
            "type": "assistant",
            "isSidechain": True,
            "message": {"content": [{
                "type": "tool_use", "name": tname, "id": tid, "input": tinp,
            }]},
        }))
    p.write_text("\n".join(lines) + "\n")
    if mtime is not None:
        os.utime(p, (mtime, mtime))
    return p


def test_scan_returns_path_and_records(tmp_path):
    jsonl = tmp_path / "ses.jsonl"
    sub = tmp_path / "ses" / "subagents"
    p = _write_agent_file(sub, "agent-a.jsonl", [
        ("Read", "t_read_1", {"file_path": "/a"}),
        ("Bash", "t_bash_1", {"command": "ls"}),
    ], mtime=1000)
    result = scan_subagent_tail(jsonl, since=0)
    assert result is not None
    newest, records = result
    assert newest == p
    assert [r["name"] for r in records] == ["Read", "Bash"]
    assert [r["id"] for r in records] == ["t_read_1", "t_bash_1"]
    assert records[0]["input"] == {"file_path": "/a"}


def test_scan_picks_mtime_newest_file(tmp_path):
    jsonl = tmp_path / "ses.jsonl"
    sub = tmp_path / "ses" / "subagents"
    _write_agent_file(sub, "agent-old.jsonl", [("Read", "t1")], mtime=1000)
    _write_agent_file(sub, "agent-new.jsonl", [("Grep", "t2")], mtime=2000)
    result = scan_subagent_tail(jsonl, since=0)
    assert result is not None
    newest, records = result
    assert newest.name == "agent-new.jsonl"
    assert records[0]["name"] == "Grep"


def test_scan_filters_by_since(tmp_path):
    jsonl = tmp_path / "ses.jsonl"
    sub = tmp_path / "ses" / "subagents"
    _write_agent_file(sub, "agent-stale.jsonl", [("Read", "t")], mtime=500)
    assert scan_subagent_tail(jsonl, since=1000) is None


def test_scan_missing_dir_returns_none(tmp_path):
    assert scan_subagent_tail(tmp_path / "nope.jsonl", since=0) is None


def test_scan_empty_file_returns_empty_records(tmp_path):
    jsonl = tmp_path / "ses.jsonl"
    sub = tmp_path / "ses" / "subagents"
    p = _write_agent_file(sub, "agent-a.jsonl", [], mtime=1000)
    result = scan_subagent_tail(jsonl, since=0)
    assert result is not None
    _, records = result
    assert records == []


def test_latest_subagent_tool_delegates(tmp_path):
    """latest_subagent_tool が共通基盤の薄い wrapper として動くことを担保。"""
    jsonl = tmp_path / "ses.jsonl"
    sub = tmp_path / "ses" / "subagents"
    _write_agent_file(sub, "agent-a.jsonl", [
        ("Read", "t1"), ("Write", "t2"), ("Bash", "t3"),
    ], mtime=1000)
    assert latest_subagent_tool(jsonl, since=0) == "Bash"
