"""scan_subagent_tail の unit test (= backend-F-18)。

subagents/ の最新 agent-*.jsonl を末尾 1 パスで scan する共通基盤。 W1-D round 2-b で
routes/subagents.py の `_scan_agent_file` がこの API に切替わる想定。 latest_subagent_tool
は本基盤の薄い wrapper として動くことを担保。
"""
import json
import os

from backend.jsonl.session_status import (
    latest_subagent_tool,
    scan_single_agent_file,
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


# --- scan_single_agent_file: backend-F-18 export for routes/subagents.py ---

def _write_agent_with_stop(path, *, tools, stop_reason):
    """末尾 assistant 行に stop_reason を持たせた agent jsonl を書く。"""
    lines = []
    for name, tid in tools:
        lines.append(json.dumps({
            "type": "assistant", "isSidechain": True,
            "message": {"content": [{
                "type": "tool_use", "name": name, "id": tid, "input": {},
            }]},
        }))
    lines.append(json.dumps({
        "type": "assistant", "isSidechain": True,
        "message": {"content": [{"type": "text", "text": "done"}],
                    "stop_reason": stop_reason},
    }))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n")


def test_scan_single_agent_file_done_after_end_turn(tmp_path):
    p = tmp_path / "subagents" / "agent-a.jsonl"
    _write_agent_with_stop(p, tools=[("Read", "t1"), ("Bash", "t2")], stop_reason="end_turn")
    r = scan_single_agent_file(p)
    assert r["lastTool"] == "Bash"
    assert r["done"] is True


def test_scan_single_agent_file_running_when_tool_use_only(tmp_path):
    p = tmp_path / "subagents" / "agent-b.jsonl"
    _write_agent_with_stop(p, tools=[("Grep", "t1")], stop_reason="tool_use")
    r = scan_single_agent_file(p)
    # stop_reason=="tool_use" は終端でない → done=False
    assert r["lastTool"] == "Grep"
    assert r["done"] is False


def test_scan_single_agent_file_handles_missing_file(tmp_path):
    r = scan_single_agent_file(tmp_path / "nope.jsonl")
    assert r["lastTool"] is None
    assert r["done"] is False
    assert r["lines_read"] == 0


def test_scan_single_agent_file_skips_bad_json(tmp_path):
    p = tmp_path / "subagents" / "agent-c.jsonl"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("not json\n" + json.dumps({
        "type": "assistant", "isSidechain": True,
        "message": {"content": [{"type": "tool_use", "name": "Read", "id": "t1"}]},
    }) + "\n")
    r = scan_single_agent_file(p)
    assert r["lastTool"] == "Read"


def test_routes_subagents_uses_new_api(tmp_path, monkeypatch):
    """routes/subagents.py の `_scan_agent_file` は scan_single_agent_file 経由で
    旧 logic と同等の戻り値を返す (= drop-in 互換)。"""
    import backend.routes.subagents as subagents_routes
    p = tmp_path / "subagents" / "agent-d.jsonl"
    _write_agent_with_stop(p, tools=[("Read", "t1")], stop_reason="end_turn")
    out = subagents_routes._scan_agent_file(p)
    assert out == {"lastTool": "Read", "done": True}
