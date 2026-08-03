"""subagents_routes の単体テスト。

サブエージェント一覧 (= meta.json ラベル + status/last_tool 推定) と個別 transcript 変換、
agent_id の path traversal 防御を確認する。
"""
import json

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import backend.routes.subagents as subagents_routes


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
    return TestClient(app), subdir, jsonl_path


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


def test_list_subagents_reports_meta_and_status(client_with_session, monkeypatch):
    client, subdir, _parent = client_with_session
    # 親 turn 実行中 = 未完了 subagent は running のまま (= 既存 scan 判定を使う)。
    monkeypatch.setattr(subagents_routes, "_session_busy", lambda sid: True)
    # done: 末尾が end_turn の assistant
    _write_agent(subdir, "agent-aaa", description="Audit imports",
                 lines=[_assistant(tool="Bash"), _assistant(text="完了", stop_reason="end_turn")])
    # running: 末尾が tool_use (= 確定 stop_reason なし)、 親 busy 中なので running
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


def test_abnormal_termination_marked_done_when_parent_idle(client_with_session, monkeypatch):
    """interrupt / API エラー / null 終了 = subagent 転写がクリーンな stop_reason 無しで終わる。
    親 turn が idle なら Task は返り済み = done (= running 固着の根治)。 親 busy 中は running。"""
    client, subdir, _parent = client_with_session
    # 末尾が stop_reason=None の assistant (= 途中で切れた終了)、 end_turn は一度も無い。
    lines = [
        _assistant(tool="Bash", stop_reason="tool_use"),
        {"type": "user", "isSidechain": True,
         "message": {"role": "user", "content": [{"type": "tool_result", "content": "ok"}]}},
        _assistant(text="partial", stop_reason=None),
    ]
    _write_agent(subdir, "agent-cut", description="Interrupted", lines=lines)

    # 親 idle → done 化する (= 実機で報告された固着の解消)。
    monkeypatch.setattr(subagents_routes, "_session_busy", lambda sid: False)
    res = client.get("/sessions/s1/subagents")
    got = {s["agentId"]: s for s in res.json()["subagents"]}
    assert got["agent-cut"]["done"] is True

    # 親 busy → まだ running (= 実際に走行中の可能性があるので誤 done にしない)。
    monkeypatch.setattr(subagents_routes, "_session_busy", lambda sid: True)
    res2 = client.get("/sessions/s1/subagents")
    got2 = {s["agentId"]: s for s in res2.json()["subagents"]}
    assert got2["agent-cut"]["done"] is False


def test_get_transcript_converts_events(client_with_session):
    client, subdir, _parent = client_with_session
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
    client, _subdir, _parent = client_with_session
    res = client.get("/sessions/s1/subagents/..%2f..%2fetc%2fpasswd/transcript")
    assert res.status_code in (400, 404)


def test_get_transcript_404_when_missing(client_with_session):
    client, _subdir, _parent = client_with_session
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


# --- backend-F-17: ETag (= file mtime+size) + If-None-Match → 304 ----------


def test_transcript_returns_etag_header(client_with_session):
    """transcript 200 応答に ETag header が付く。"""
    client, subdir, _parent = client_with_session
    _write_agent(subdir, "agent-aaa", description="X", lines=[
        _assistant(text="hi", stop_reason="end_turn"),
    ])
    res = client.get("/sessions/s1/subagents/agent-aaa/transcript")
    assert res.status_code == 200
    etag = res.headers.get("etag")
    assert etag and etag.startswith('W/"')


def test_transcript_304_on_matching_if_none_match(client_with_session):
    """If-None-Match に同 ETag を送ると 304 (= body 無し)。"""
    client, subdir, _parent = client_with_session
    _write_agent(subdir, "agent-bbb", description="Y", lines=[
        _assistant(text="hi", stop_reason="end_turn"),
    ])
    res1 = client.get("/sessions/s1/subagents/agent-bbb/transcript")
    etag = res1.headers["etag"]
    res2 = client.get(
        "/sessions/s1/subagents/agent-bbb/transcript",
        headers={"If-None-Match": etag},
    )
    assert res2.status_code == 304
    # 304 でも ETag は返す (= HTTP RFC 準拠)
    assert res2.headers.get("etag") == etag
    # 304 は body 無し (= 空)
    assert res2.content == b""


def test_transcript_changes_etag_on_file_mutation(client_with_session):
    """transcript が append されたら ETag が変わる (= 304 が誤って続かない)。"""
    client, subdir, _parent = client_with_session
    _write_agent(subdir, "agent-ccc", description="Z", lines=[
        _assistant(text="line1", stop_reason="end_turn"),
    ])
    res1 = client.get("/sessions/s1/subagents/agent-ccc/transcript")
    etag1 = res1.headers["etag"]
    # 同 file に追記 (= 走行中 transcript の append-only 想定)
    f = subdir / "agent-ccc.jsonl"
    with f.open("a") as fh:
        fh.write('{"type": "assistant", "isSidechain": true, '
                 '"message": {"role": "assistant", "content": [{"type": "text", "text": "more"}], '
                 '"stop_reason": "end_turn"}}\n')
    res2 = client.get(
        "/sessions/s1/subagents/agent-ccc/transcript",
        headers={"If-None-Match": etag1},
    )
    # 内容が変わったので 304 にならず 200 + 新 ETag
    assert res2.status_code == 200
    assert res2.headers["etag"] != etag1


# --- running settle: 未完了がいる間は再スキャンして done 固着を防ぐ (= 2026-07-09) ---

def test_payload_has_running_detects_unfinished_subagent():
    from backend.routes.subagents import _payload_has_running
    assert _payload_has_running({"subagents": [{"done": False}], "workflows": []}) is True
    assert _payload_has_running({"subagents": [{"done": True}], "workflows": []}) is False
    assert _payload_has_running({"subagents": [], "workflows": []}) is False


def test_payload_has_running_detects_running_workflow():
    from backend.routes.subagents import _payload_has_running
    assert _payload_has_running({"subagents": [], "workflows": [{"status": "running"}]}) is True
    assert _payload_has_running({"subagents": [], "workflows": [{"status": "completed"}]}) is False


def test_payload_has_running_mixed():
    from backend.routes.subagents import _payload_has_running
    # 完了 subagent + 完了 workflow = settle 不要
    assert _payload_has_running({
        "subagents": [{"done": True}, {"done": True}],
        "workflows": [{"status": "completed"}],
    }) is False
    # 1 つでも未完了なら settle 継続
    assert _payload_has_running({
        "subagents": [{"done": True}, {"done": False}],
        "workflows": [{"status": "completed"}],
    }) is True


def _write_agent_with_tool_use_id(subdir, agent_id, tool_use_id, *, lines):
    (subdir / f"{agent_id}.meta.json").write_text(json.dumps({
        "agentType": "general-purpose", "description": agent_id, "toolUseId": tool_use_id,
    }))
    with (subdir / f"{agent_id}.jsonl").open("w") as fh:
        for ln in lines:
            fh.write(json.dumps(ln) + "\n")


def _parent_tool_result(parent_path, tool_use_id):
    with parent_path.open("a") as fh:
        fh.write(json.dumps({
            "type": "user",
            "message": {"role": "user", "content": [
                {"type": "tool_result", "tool_use_id": tool_use_id, "content": "ok"},
            ]},
        }) + "\n")


# 背景実行の subagent は親 turn が終わった後も走り続ける。 「親 idle = 返り済み」 で代用すると
# 走行中のものが軒並み done 表示になる (= 2026-08-03 実機報告)。 結果が親転写に返ったかどうかが
# 唯一の厳密な印。
def test_running_subagent_stays_running_while_the_parent_is_idle(client_with_session, monkeypatch):
    client, subdir, _parent = client_with_session
    monkeypatch.setattr(subagents_routes, "_session_busy", lambda sid: False)
    _write_agent_with_tool_use_id(subdir, "agent-bg1", "toolu_bg1",
                                  lines=[_assistant(tool="Grep", stop_reason="tool_use")])
    got = {s["agentId"]: s for s in client.get("/sessions/s1/subagents").json()["subagents"]}
    assert got["agent-bg1"]["done"] is False


def test_subagent_is_done_once_its_result_comes_back(client_with_session, monkeypatch):
    client, subdir, parent = client_with_session
    monkeypatch.setattr(subagents_routes, "_session_busy", lambda sid: False)
    _write_agent_with_tool_use_id(subdir, "agent-bg2", "toolu_bg2",
                                  lines=[_assistant(tool="Grep", stop_reason="tool_use")])
    _parent_tool_result(parent, "toolu_bg2")
    got = {s["agentId"]: s for s in client.get("/sessions/s1/subagents").json()["subagents"]}
    assert got["agent-bg2"]["done"] is True


def test_result_for_another_task_does_not_complete_this_one(client_with_session, monkeypatch):
    client, subdir, parent = client_with_session
    monkeypatch.setattr(subagents_routes, "_session_busy", lambda sid: False)
    _write_agent_with_tool_use_id(subdir, "agent-bg3", "toolu_bg3",
                                  lines=[_assistant(tool="Grep", stop_reason="tool_use")])
    _parent_tool_result(parent, "toolu_someone_else")
    got = {s["agentId"]: s for s in client.get("/sessions/s1/subagents").json()["subagents"]}
    assert got["agent-bg3"]["done"] is False


def test_a_cleanly_finished_subagent_is_done_without_any_parent_result(client_with_session, monkeypatch):
    client, subdir, _parent = client_with_session
    monkeypatch.setattr(subagents_routes, "_session_busy", lambda sid: False)
    _write_agent_with_tool_use_id(subdir, "agent-bg4", "toolu_bg4",
                                  lines=[_assistant(text="done", stop_reason="end_turn")])
    got = {s["agentId"]: s for s in client.get("/sessions/s1/subagents").json()["subagents"]}
    assert got["agent-bg4"]["done"] is True


def _parent_launch_ack(parent_path, tool_use_id, agent_id):
    """背景実行の Task が起動直後に返す ack (= 完了印ではない)。"""
    with parent_path.open("a") as fh:
        fh.write(json.dumps({
            "type": "user",
            "message": {"role": "user", "content": [{
                "type": "tool_result", "tool_use_id": tool_use_id,
                "content": [{"type": "text", "text":
                             f"Async agent launched successfully. (internal metadata)\nagentId: {agent_id}\n"
                             "The agent is working in the background."}],
            }]},
        }) + "\n")


def test_launch_ack_does_not_count_as_completion(client_with_session, monkeypatch):
    """背景実行は起動の瞬間に tool_result が返る。 これを完了印にすると、 走行中の subagent が
    軒並み done になる (= 2026-08-03 実機報告、 親 idle 代用を直した後に別経路で再発した形)。"""
    client, subdir, parent = client_with_session
    monkeypatch.setattr(subagents_routes, "_session_busy", lambda sid: False)
    _write_agent_with_tool_use_id(subdir, "agent-bg5", "toolu_bg5",
                                  lines=[_assistant(tool="Grep", stop_reason="tool_use")])
    _parent_launch_ack(parent, "toolu_bg5", "agent-bg5")
    got = {s["agentId"]: s for s in client.get("/sessions/s1/subagents").json()["subagents"]}
    assert got["agent-bg5"]["done"] is False


def test_background_subagent_completes_via_its_own_transcript(client_with_session, monkeypatch):
    """背景実行の完了は subagent 自身の確定 stop_reason で拾う (= ack は返ったままでよい)。"""
    client, subdir, parent = client_with_session
    monkeypatch.setattr(subagents_routes, "_session_busy", lambda sid: False)
    _write_agent_with_tool_use_id(subdir, "agent-bg6", "toolu_bg6",
                                  lines=[_assistant(tool="Grep", stop_reason="tool_use"),
                                         _assistant(text="done", stop_reason="end_turn")])
    _parent_launch_ack(parent, "toolu_bg6", "agent-bg6")
    got = {s["agentId"]: s for s in client.get("/sessions/s1/subagents").json()["subagents"]}
    assert got["agent-bg6"]["done"] is True


def test_a_real_result_still_counts_as_completion(client_with_session, monkeypatch):
    """同期実行の Task は実結果が返る。 これは従来どおり完了印。"""
    client, subdir, parent = client_with_session
    monkeypatch.setattr(subagents_routes, "_session_busy", lambda sid: False)
    _write_agent_with_tool_use_id(subdir, "agent-sync1", "toolu_sync1",
                                  lines=[_assistant(tool="Grep", stop_reason="tool_use")])
    _parent_tool_result(parent, "toolu_sync1")
    got = {s["agentId"]: s for s in client.get("/sessions/s1/subagents").json()["subagents"]}
    assert got["agent-sync1"]["done"] is True
