"""`POST /debug/e2e/seed` (= playwright の試験がタブと記録を 1 回で置く口)。

tmux と claude は立てない。 記録の置き場と結び付けを差し替えて、 同じタブを seed し直した時に前の seed の
会話が残らないこと (= 試験どうしが同じタブを使い回しても、 前の試験の吹き出しが出ない) を見る。
"""
from __future__ import annotations

import pytest
from fastapi import FastAPI
from starlette.testclient import TestClient

import backend._common.config as config_mod
from backend.jsonl import history
from backend.jsonl import jsonl_watcher
from backend.jsonl import routes as jsonl_routes
from backend.routes import debug_e2e

SID = "ses_e2eseed"


@pytest.fixture
def seeded_paths(monkeypatch, tmp_path, isolated_state) -> list[str]:
    """seed の口が結び付けた記録の path の並び。 記録の置き場と控えは tmp_path の下。"""
    monkeypatch.setenv("CPC_E2E", "1")
    monkeypatch.setattr(history, "SESSION_HISTORY_PATH", tmp_path / "session_history.json")
    monkeypatch.setattr(config_mod, "projects_dir_for_account", lambda account_id: tmp_path / "projects")

    agents = {"agent_e2e": {"cwd": str(tmp_path / "cwd")}}

    async def agents_snapshot() -> dict:
        return agents

    monkeypatch.setattr(debug_e2e, "_agents_snapshot", agents_snapshot)
    monkeypatch.setattr(isolated_state, "_agents", lambda: agents)
    monkeypatch.setattr(debug_e2e, "set_tier", lambda sid, tier: None)
    bound: list[str] = []
    monkeypatch.setattr(jsonl_watcher, "confirm_bind", lambda sid, claude_sid, path: bound.append(path))
    jsonl_routes._sid_tail_reset_pending.clear()
    yield bound
    jsonl_routes._sid_tail_reset_pending.clear()


@pytest.fixture
def client() -> TestClient:
    app = FastAPI()
    app.include_router(debug_e2e.router)
    return TestClient(app, client=("127.0.0.1", 50000), base_url="http://localhost")


def _seed(client: TestClient, text: str) -> dict:
    event = {"type": "user", "uuid": f"u-{text}", "message": {"role": "user", "content": text}}
    res = client.post("/debug/e2e/seed", json={"sid": SID, "jsonl_events": [event]})
    assert res.status_code == 200, res.text
    return res.json()


def test_seeding_a_tab_again_leaves_nothing_of_the_last_seed(client, seeded_paths):
    first = _seed(client, "first")
    # 見張りは、 結び直しで記録の path が変わったのを見ると前の記録を「終わった会話」 として積む
    history.record_end(SID, first["claude_sid"], jsonl_path=first["jsonl_path"])
    jsonl_routes._sid_tail_reset_pending.clear()

    second = _seed(client, "second")

    assert seeded_paths == [first["jsonl_path"], second["jsonl_path"]]
    assert history.ended(SID) == []
    assert history.next_base(SID) == 0
    # 見張りは次の回にこのタブの状態を捨てる (= 前の path を知らないので、 控えに積み直さない)
    assert SID in jsonl_routes._sid_tail_reset_pending
