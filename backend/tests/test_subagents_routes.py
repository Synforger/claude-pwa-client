"""subagents_routes の単体テスト。

サブエージェント一覧 (= meta.json ラベル + status/last_tool 推定) と個別 transcript 変換、
agent_id の path traversal 防御を確認する。
"""
import json

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import subagents_routes


def _write_agent(subdir, agent_id, *, description, lines):
    (subdir / f"{agent_id}.meta.json").write_text(
        json.dumps({"agentType": "general-purpose", "description": description})
    )
    with (subdir / f"{agent_id}.jsonl").open("w") as fh:
        for ln in lines:
            fh.write(json.dumps(ln) + "\n")


@pytest.fixture
def client_with_session(tmp_path, monkeypatch):
    """fake jsonl path を張り、 その subagents/ に agent ファイルを置く。"""
    jsonl_path = tmp_path / "sess.jsonl"
    jsonl_path.write_text("")
    subdir = tmp_path / "sess" / "subagents"
    subdir.mkdir(parents=True)
    monkeypatch.setattr(subagents_routes, "jsonl_path_for_session", lambda sid: jsonl_path)
    app = FastAPI()
    app.include_router(subagents_routes.router)
    return TestClient(app), subdir


def _assistant(text=None, tool=None, stop_reason=None):
    content = []
    if text is not None:
        content.append({"type": "text", "text": text})
    if tool is not None:
        content.append({"type": "tool_use", "name": tool, "id": "t1", "input": {}})
    return {"type": "assistant", "isSidechain": True,
            "message": {"role": "assistant", "content": content, "stop_reason": stop_reason}}


def test_list_subagents_empty_when_no_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(subagents_routes, "jsonl_path_for_session", lambda sid: tmp_path / "none.jsonl")
    app = FastAPI()
    app.include_router(subagents_routes.router)
    client = TestClient(app)
    res = client.get("/sessions/s1/subagents")
    assert res.status_code == 200
    assert res.json() == {"subagents": [], "workflows": []}


def test_list_subagents_reports_meta_and_status(client_with_session):
    client, subdir = client_with_session
    # done: 末尾が end_turn の assistant
    _write_agent(subdir, "agent-aaa", description="Audit imports",
                 lines=[_assistant(tool="Bash"), _assistant(text="完了", stop_reason="end_turn")])
    # running: 末尾が tool_use (= 確定 stop_reason なし)
    _write_agent(subdir, "agent-bbb", description="Rewrite docs",
                 lines=[_assistant(tool="Grep", stop_reason="tool_use")])
    res = client.get("/sessions/s1/subagents")
    assert res.status_code == 200
    by_id = {s["agentId"]: s for s in res.json()["subagents"]}
    assert by_id["agent-aaa"]["description"] == "Audit imports"
    assert by_id["agent-aaa"]["done"] is True
    assert by_id["agent-aaa"]["lastTool"] == "Bash"
    assert by_id["agent-bbb"]["done"] is False
    assert by_id["agent-bbb"]["lastTool"] == "Grep"


def test_get_transcript_converts_events(client_with_session):
    client, subdir = client_with_session
    _write_agent(subdir, "agent-ccc", description="Task X", lines=[
        {"type": "user", "isSidechain": True, "message": {"role": "user", "content": "do the thing"}},
        _assistant(text="done", stop_reason="end_turn"),
    ])
    res = client.get("/sessions/s1/subagents/agent-ccc/transcript")
    assert res.status_code == 200
    data = res.json()
    assert data["description"] == "Task X"
    types = [e["type"] for e in data["events"]]
    # sidechain でも user_message / assistant が出る (= 親 chat の skip と違い中身を見せる)
    assert "user_message" in types
    assert "assistant" in types


def test_get_transcript_rejects_bad_agent_id(client_with_session):
    client, _ = client_with_session
    res = client.get("/sessions/s1/subagents/..%2f..%2fetc%2fpasswd/transcript")
    assert res.status_code in (400, 404)


def test_get_transcript_404_when_missing(client_with_session):
    client, _ = client_with_session
    res = client.get("/sessions/s1/subagents/agent-missing/transcript")
    assert res.status_code == 404


# --- Workflow run (= グループ化、 105 agent 規模の畳み込み) ---

@pytest.fixture
def client_with_base(tmp_path, monkeypatch):
    """session base (= subagents/ と workflows/ が並ぶ) を張る。"""
    jsonl_path = tmp_path / "sess.jsonl"
    jsonl_path.write_text("")
    base = tmp_path / "sess"
    (base / "subagents").mkdir(parents=True)
    (base / "workflows").mkdir(parents=True)
    monkeypatch.setattr(subagents_routes, "jsonl_path_for_session", lambda sid: jsonl_path)
    app = FastAPI()
    app.include_router(subagents_routes.router)
    return TestClient(app), base


def test_list_includes_workflow_run_as_group(client_with_base):
    client, base = client_with_base
    (base / "workflows" / "wf_abc123-x.json").write_text(json.dumps({
        "runId": "wf_abc123-x", "taskId": "wgms5lj4t", "workflowName": "deep-research",
        "status": "killed", "agentCount": 105, "totalTokens": 2310845, "durationMs": 446740,
        "phases": [{"title": "Scope"}, {"title": "Search"}], "error": "aborted",
    }))
    res = client.get("/sessions/s1/subagents")
    assert res.status_code == 200
    wfs = res.json()["workflows"]
    assert len(wfs) == 1
    w = wfs[0]
    assert w["runId"] == "wf_abc123-x"
    # taskId は親チャットの Workflow tool_result "Task ID: ..." と突き合わせる引き当てキー
    assert w["taskId"] == "wgms5lj4t"
    assert w["workflowName"] == "deep-research"
    assert w["agentCount"] == 105
    assert w["status"] == "killed"
    assert w["phaseTitles"] == ["Scope", "Search"]
    assert w["hasError"] is True


def test_list_workflow_agents_from_journal(client_with_base):
    client, base = client_with_base
    run_dir = base / "subagents" / "workflows" / "wf_abc123-x"
    run_dir.mkdir(parents=True)
    with (run_dir / "journal.jsonl").open("w") as fh:
        fh.write(json.dumps({"type": "started", "agentId": "a1"}) + "\n")
        fh.write(json.dumps({"type": "result", "agentId": "a1",
                             "result": {"summary": "Searched SOTA methods"}}) + "\n")
        fh.write(json.dumps({"type": "started", "agentId": "a2"}) + "\n")  # まだ running
    res = client.get("/sessions/s1/workflows/wf_abc123-x/agents")
    assert res.status_code == 200
    agents = res.json()["agents"]
    # journal の agentId (prefix 無し) は実ファイル名に合わせ "agent-" 付きで返る
    assert [a["agentId"] for a in agents] == ["agent-a1", "agent-a2"]
    assert agents[0]["done"] is True
    assert agents[0]["label"] == "Searched SOTA methods"
    assert agents[1]["done"] is False


def test_journal_label_falls_back_to_keys():
    # summary 系が無い structured output は上位キー名を型ヒントとして出す
    assert subagents_routes._journal_result_label({"claims": [], "sourceQuality": 1}) == "{claims, sourceQuality}"
    assert subagents_routes._journal_result_label({"summary": "ok"}) == "ok"
    assert subagents_routes._journal_result_label("plain text") == "plain text"


def test_workflow_agent_transcript_via_wf_param(client_with_base):
    client, base = client_with_base
    run_dir = base / "subagents" / "workflows" / "wf_abc123-x"
    run_dir.mkdir(parents=True)
    with (run_dir / "agent-aaa.jsonl").open("w") as fh:
        fh.write(json.dumps(_assistant(text="result text", stop_reason="end_turn")) + "\n")
    res = client.get("/sessions/s1/subagents/agent-aaa/transcript", params={"wf": "wf_abc123-x"})
    assert res.status_code == 200
    assert any(e["type"] == "assistant" for e in res.json()["events"])


def test_list_includes_running_workflow_without_manifest(client_with_base):
    # マニフェスト wf_<id>.json は完了時にしか書かれない。 走行中は journal.jsonl だけが
    # 先に存在するので、 そこから「running + 起動済 agent 数」 を拾って一覧に出す。
    client, base = client_with_base
    run_dir = base / "subagents" / "workflows" / "wf_running-abc"
    run_dir.mkdir(parents=True)
    with (run_dir / "journal.jsonl").open("w") as fh:
        fh.write(json.dumps({"type": "started", "agentId": "a1"}) + "\n")
        fh.write(json.dumps({"type": "started", "agentId": "a2"}) + "\n")
    res = client.get("/sessions/s1/subagents")
    assert res.status_code == 200
    wfs = res.json()["workflows"]
    assert len(wfs) == 1
    w = wfs[0]
    assert w["runId"] == "wf_running-abc"
    assert w["status"] == "running"
    assert w["agentCount"] == 2
    # マニフェスト由来項目は走行中は None
    assert w["taskId"] is None
    assert w["workflowName"] is None
    assert w["phaseTitles"] == []


def test_list_workflow_manifest_takes_precedence_over_running(client_with_base):
    # 同じ runId にマニフェストと journal の両方がある場合 (= 完了直後) はマニフェスト側を
    # 採用する (= status:completed 等のリッチな情報を優先)。
    client, base = client_with_base
    (base / "workflows" / "wf_done-xyz.json").write_text(json.dumps({
        "runId": "wf_done-xyz", "workflowName": "deep-research",
        "status": "completed", "agentCount": 3,
    }))
    run_dir = base / "subagents" / "workflows" / "wf_done-xyz"
    run_dir.mkdir(parents=True)
    (run_dir / "journal.jsonl").write_text(
        json.dumps({"type": "started", "agentId": "a1"}) + "\n"
    )
    res = client.get("/sessions/s1/subagents")
    wfs = res.json()["workflows"]
    assert len(wfs) == 1
    assert wfs[0]["status"] == "completed"
    assert wfs[0]["agentCount"] == 3


def test_workflow_endpoints_reject_bad_run_id(client_with_base):
    client, _ = client_with_base
    assert client.get("/sessions/s1/workflows/..%2f..%2fetc/agents").status_code in (400, 404)
    assert client.get(
        "/sessions/s1/subagents/agent-aaa/transcript", params={"wf": "../escape"},
    ).status_code == 400
