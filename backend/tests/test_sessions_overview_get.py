"""`GET /sessions/overview` が、 stream の overview と同じ中身を 1 回で返すか (= iPhone のウィジェットが引く)。"""
from fastapi import FastAPI
from fastapi.testclient import TestClient

import backend.routes.overview as overview
import backend.state as state_mod


def test_overview_get_matches_the_stream_payload(isolated_state):
    for sid in ("ses_w1", "ses_w2"):
        state_mod.stream_states[sid] = state_mod.StreamState(agent_id="a")
        state_mod.sessions_meta[sid] = state_mod.SessionDef(id=sid, agent_id="a", title=sid, created_at=0)
    state_mod.stream_states["ses_w1"].busy = True
    app = FastAPI()
    app.include_router(overview.router)
    body = TestClient(app).get("/sessions/overview").json()
    assert body == overview._build_sessions_overview()
    assert set(body) == {"ses_w1", "ses_w2"}
    assert body["ses_w1"]["busy"] is True and body["ses_w2"]["busy"] is False
