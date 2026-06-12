"""サブエージェント (= Task で起動した子 agent) の一覧と個別 transcript を返す。

各サブエージェントは `<jsonl>/<session>/subagents/agent-<id>.jsonl` に全文 (isSidechain=True)
を書き、 隣の `agent-<id>.meta.json` に `{"agentType", "description"}` を書く。 親 chat には
sidechain を混ぜない方針 (= jsonl_events が skip) なので、 中身を見たい時はこの専用経路で引く。

第一版はセッション単位のフラットな一覧 (= 親 Task 呼び出し単位のグルーピングはしない):
subagent の先頭行に親 turn を指す安定キーが無く (parentUuid=None 実績)、 Task tool_use id ↔
agentId の素直な対応が取れないため。
"""
import json
import logging
import re
from pathlib import Path

from fastapi import APIRouter, HTTPException

from jsonl.events import subagent_line_to_events
from terminal.runner import jsonl_path_for_session

logger = logging.getLogger(__name__)
router = APIRouter()

# ファイル名は agent-<hex>.jsonl 固定。 path traversal を防ぐため id をこの形に限定する。
_AGENT_ID_RE = re.compile(r"^agent-[A-Za-z0-9]+$")
# 1 transcript あたりの行数上限 (= 暴走 agent の巨大ログでメモリを食わない安全弁)。
_MAX_TRANSCRIPT_LINES = 5000


# Workflow の run id (= ディレクトリ名 / クエリ値) を path traversal から守るための形式。
_RUN_ID_RE = re.compile(r"^wf_[A-Za-z0-9-]+$")


def _session_base(session_id: str) -> Path | None:
    """セッションの状態ディレクトリ (= <project>/<session>/) を返す。

    配下に subagents/ (= Task の子 agent) と workflows/ (= Workflow run のマニフェスト) が並ぶ。
    """
    jp = jsonl_path_for_session(session_id)
    if jp is None:
        return None
    return jp.parent / jp.stem


def _subagents_dir(session_id: str) -> Path | None:
    base = _session_base(session_id)
    return base / "subagents" if base is not None else None


def _scan_agent_file(path: Path) -> dict:
    """agent jsonl を 1 パスして status / last_tool を求める。

    - last_tool: 最後に現れた tool_use の name (= 実行中なら「今やってる処理」)
    - done: 最後に出た **確定 stop_reason** (= tool_use 以外) より後に tool_result が無い

    旧実装は assistant 行のたびに done を再評価 → 直後の null stop_reason 行で
    false に上書きされる罠があり、 走り終わったエージェントが running のまま固まる
    ことがあった。 1 パス回して「最後の確定 stop_reason の index」 と「最後の
    tool_result の index」 を比較する方式に変更 (2026-06-12)。
    """
    last_tool: str | None = None
    last_stop_idx = -1
    last_tool_result_idx = -1
    try:
        with path.open() as fh:
            for i, raw in enumerate(fh):
                try:
                    line = json.loads(raw)
                except json.JSONDecodeError:
                    continue
                msg = line.get("message") or {}
                content = msg.get("content")
                if isinstance(content, list):
                    for b in content:
                        if isinstance(b, dict) and b.get("type") == "tool_use":
                            name = b.get("name")
                            if name:
                                last_tool = name
                if line.get("type") == "assistant":
                    sr = msg.get("stop_reason")
                    if sr and sr != "tool_use":
                        last_stop_idx = i
                elif isinstance(content, list) and any(
                    isinstance(b, dict) and b.get("type") == "tool_result" for b in content
                ):
                    last_tool_result_idx = i
    except OSError:
        pass
    # 確定 stop_reason があって、 その後に tool_result が無ければ完了
    done = last_stop_idx >= 0 and last_stop_idx > last_tool_result_idx
    return {"lastTool": last_tool, "done": done}


def _read_meta(meta_path: Path) -> dict:
    try:
        data = json.loads(meta_path.read_text())
        return {
            "agentType": data.get("agentType"),
            "description": data.get("description"),
        }
    except (OSError, json.JSONDecodeError):
        return {"agentType": None, "description": None}


def _running_workflow_from_journal(run_dir: Path) -> dict | None:
    """走行中 (= マニフェスト未生成) の Workflow run を journal.jsonl から要約する。

    マニフェスト wf_<id>.json は完了時にしか書かれないので、 起動直後 〜 完走前は
    subagents/workflows/<runId>/journal.jsonl だけが存在する。 ここから「いま動いてる」
    旨と起動済 agent 数だけ拾って一覧に出す (workflowName/taskId/phaseTitles 等の
    マニフェスト由来項目は不明 = None)。
    """
    journal = run_dir / "journal.jsonl"
    if not journal.is_file():
        return None
    started: set[str] = set()
    try:
        with journal.open() as fh:
            for raw in fh:
                try:
                    ev = json.loads(raw)
                except json.JSONDecodeError:
                    continue
                if ev.get("type") == "started":
                    aid = ev.get("agentId")
                    if aid:
                        started.add(aid)
    except OSError:
        return None
    return {
        "runId": run_dir.name,
        "taskId": None,
        "workflowName": None,
        "status": "running",
        "agentCount": len(started) or None,
        "totalTokens": None,
        "totalToolCalls": None,
        "durationMs": None,
        "phaseTitles": [],
        "hasError": False,
        "mtime": journal.stat().st_mtime,
    }


def _list_workflows(base: Path) -> list[dict]:
    """workflows/<runId>.json マニフェスト + 走行中 run journal の両方を Workflow 一覧として返す。

    マニフェスト (= 完了時生成) がある run は workflowName / agentCount / totalTokens 等の
    リッチな要約で、 まだマニフェストが書かれていない走行中 run は subagents/workflows/<runId>/
    journal.jsonl から「running + 起動済 agent 数」 だけ取って同じ一覧に並べる。 これにより
    投げた直後の workflow も 🤖 パネルから見える。

    105 agent 規模でも 1 行に畳めるよう、 個別 agent でなく run 単位の要約 (= 名前 / 件数 /
    status / token / 所要) を出す。 agent 個別は別エンドポイントで run を drill-down する。
    """
    runs: list[dict] = []
    seen_run_ids: set[str] = set()
    wf_dir = base / "workflows"
    if wf_dir.is_dir():
        for manifest in wf_dir.glob("wf_*.json"):
            run_id = manifest.stem
            if not _RUN_ID_RE.match(run_id):
                continue
            try:
                d = json.loads(manifest.read_text())
            except (OSError, json.JSONDecodeError):
                continue
            phases = d.get("phases") or []
            runs.append({
                "runId": run_id,
                # 親チャットの Workflow tool_result が "Task ID: <taskId>" を含むので、
                # frontend はこの taskId で run を引き当ててスコープ表示する。
                "taskId": d.get("taskId"),
                "workflowName": d.get("workflowName"),
                "status": d.get("status"),
                "agentCount": d.get("agentCount"),
                "totalTokens": d.get("totalTokens"),
                "totalToolCalls": d.get("totalToolCalls"),
                "durationMs": d.get("durationMs"),
                "phaseTitles": [p.get("title") for p in phases if isinstance(p, dict)],
                "hasError": bool(d.get("error")),
                "mtime": manifest.stat().st_mtime,
            })
            seen_run_ids.add(run_id)
    # 走行中 run (= マニフェスト未生成、 journal だけ存在) を拾う
    wf_runs_dir = base / "subagents" / "workflows"
    if wf_runs_dir.is_dir():
        for run_dir in wf_runs_dir.iterdir():
            if not run_dir.is_dir():
                continue
            run_id = run_dir.name
            if not _RUN_ID_RE.match(run_id) or run_id in seen_run_ids:
                continue
            entry = _running_workflow_from_journal(run_dir)
            if entry is not None:
                runs.append(entry)
    runs.sort(key=lambda x: x["mtime"], reverse=True)
    return runs


@router.get("/sessions/{session_id}/subagents")
def list_subagents(session_id: str):
    """セッションの Task subagent (フラット) + Workflow run (グループ) 一覧を新しい順で返す。"""
    base = _session_base(session_id)
    if base is None:
        return {"subagents": [], "workflows": []}
    subdir = base / "subagents"
    items = []
    if subdir.is_dir():
        # 非再帰 glob: Workflow agent (= subagents/workflows/<run>/) は拾わない。 それらは
        # _list_workflows + run drill-down 側で扱うため、 ここはフラットな Task subagent のみ。
        for jsonl_file in subdir.glob("agent-*.jsonl"):
            agent_id = jsonl_file.stem
            if not _AGENT_ID_RE.match(agent_id):
                continue
            meta = _read_meta(jsonl_file.with_suffix(".meta.json"))
            scan = _scan_agent_file(jsonl_file)
            items.append({
                "agentId": agent_id,
                "agentType": meta["agentType"],
                "description": meta["description"],
                "lastTool": scan["lastTool"],
                "done": scan["done"],
                "mtime": jsonl_file.stat().st_mtime,
            })
    items.sort(key=lambda x: x["mtime"], reverse=True)
    return {"subagents": items, "workflows": _list_workflows(base)}


@router.get("/sessions/{session_id}/workflows/{run_id}/agents")
def list_workflow_agents(session_id: str, run_id: str):
    """1 Workflow run の agent 一覧を journal.jsonl から組む (= 105 ファイルを開かず index 1 本)。

    journal は agent ごとに started → result の順で書かれ、 result に各 agent の返した
    summary が載る (= 一覧ラベルに最適)。 result が来てなければ running 扱い。
    """
    if not _RUN_ID_RE.match(run_id):
        raise HTTPException(status_code=400, detail="Invalid run id")
    base = _session_base(session_id)
    if base is None:
        raise HTTPException(status_code=404, detail="Session not found")
    run_dir = base / "subagents" / "workflows" / run_id
    if not run_dir.resolve().is_relative_to((base / "subagents" / "workflows").resolve()):
        raise HTTPException(status_code=403, detail="Access denied")
    journal = run_dir / "journal.jsonl"
    if not journal.is_file():
        raise HTTPException(status_code=404, detail="Workflow not found")
    agents: dict[str, dict] = {}
    order: list[str] = []
    try:
        with journal.open() as fh:
            for raw in fh:
                try:
                    ev = json.loads(raw)
                except json.JSONDecodeError:
                    continue
                aid = ev.get("agentId")
                if not aid:
                    continue
                if aid not in agents:
                    # journal の agentId は prefix 無し (= "a20bbf...")。 実ファイルは
                    # agent-<id>.jsonl なので、 transcript 取得 (= _AGENT_ID_RE / ファイル名) と
                    # 揃うよう "agent-" を付けて返す。
                    agents[aid] = {"agentId": f"agent-{aid}", "label": None, "done": False}
                    order.append(aid)
                if ev.get("type") == "result":
                    agents[aid]["done"] = True
                    agents[aid]["label"] = _journal_result_label(ev.get("result"))
    except OSError:
        raise HTTPException(status_code=500, detail="Internal error")
    return {"runId": run_id, "agents": [agents[a] for a in order]}


def _journal_result_label(result) -> str | None:
    """journal の result から一覧ラベルを 1 行で作る。 dict なら summary 優先、 str ならそのまま。"""
    if isinstance(result, dict):
        for k in ("summary", "title", "description"):
            v = result.get(k)
            if isinstance(v, str) and v.strip():
                return v.strip()[:200]
        # summary 系が無い structured output (= {claims, sourceQuality} 等) は上位キー名を
        # 型ヒントとして出す。 全文は transcript を開けば読めるので一覧はこれで十分。
        keys = list(result.keys())
        if keys:
            return "{" + ", ".join(keys[:4]) + "}"
        return None
    if isinstance(result, str) and result.strip():
        return result.strip()[:200]
    return None


@router.get("/sessions/{session_id}/subagents/{agent_id}/transcript")
def get_subagent_transcript(session_id: str, agent_id: str, wf: str | None = None):
    """個別サブエージェントの transcript を表示用 event 列に変換して返す。

    wf (= Workflow run id) 指定時は subagents/workflows/<wf>/ 配下を読む (= Workflow agent)。
    未指定なら subagents/ 直下 (= 通常の Task subagent)。
    """
    if not _AGENT_ID_RE.match(agent_id):
        raise HTTPException(status_code=400, detail="Invalid agent id")
    subdir = _subagents_dir(session_id)
    if subdir is None:
        raise HTTPException(status_code=404, detail="Session not found")
    if wf is not None:
        if not _RUN_ID_RE.match(wf):
            raise HTTPException(status_code=400, detail="Invalid run id")
        parent = subdir / "workflows" / wf
    else:
        parent = subdir
    jsonl_file = parent / f"{agent_id}.jsonl"
    # resolve 後に想定ディレクトリ配下か再検査 (= agent_id / wf 正規表現で防ぐが二重防御)
    if not jsonl_file.resolve().is_relative_to(parent.resolve()):
        raise HTTPException(status_code=403, detail="Access denied")
    if not jsonl_file.is_file():
        raise HTTPException(status_code=404, detail="Transcript not found")
    events: list[dict] = []
    try:
        with jsonl_file.open() as fh:
            for i, raw in enumerate(fh):
                if i >= _MAX_TRANSCRIPT_LINES:
                    break
                try:
                    line = json.loads(raw)
                except json.JSONDecodeError:
                    continue
                events.extend(subagent_line_to_events(line))
    except OSError:
        logger.exception("failed to read subagent transcript: %s", jsonl_file)
        raise HTTPException(status_code=500, detail="Internal error")
    meta = _read_meta(jsonl_file.with_suffix(".meta.json"))
    return {"agentId": agent_id, **meta, "events": events}
