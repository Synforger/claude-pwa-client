"""ADR-012 /debug/* endpoint の認可 (= localhost + Host allowlist 2 段防御) と動作検証。

DNS rebinding 攻撃 (= ローカルブラウザを攻撃 site の DNS 経由で backend に向ける) を Host header
allowlist で 403 にする。 TestClient の Host header は既定 "testserver" なので、 通常呼出は
403、 明示的に "localhost" / "127.0.0.1" を渡したものは 200 を期待する形で test する。
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI
from starlette.testclient import TestClient

from backend.observability import event_journal as ej
from backend.observability.event_journal import record
from backend.routes import debug as debug_routes


@pytest.fixture
def app_with_debug(monkeypatch: pytest.MonkeyPatch) -> FastAPI:
    """debug router だけを mount した最小 FastAPI app (= main の lifespan を起動させない、
    OOM 回避)。 starlette TestClient の peer は "testclient" を名乗るので、 test 中だけ peer
    allowlist に追加する (= production では loopback 3 種のみ)。
    """
    monkeypatch.setattr(
        debug_routes,
        "ALLOWED_PEERS",
        debug_routes.ALLOWED_PEERS | {"testclient"},
    )
    app = FastAPI()
    app.include_router(debug_routes.router)
    return app


@pytest.fixture(autouse=True)
def _isolate_logs_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(ej, "LOGS_DIR", tmp_path)
    ej._sequencer.reset()
    yield tmp_path


# --- Host allowlist parse -----------------------------------------------


def test_host_check_accepts_localhost_variants():
    assert debug_routes._host_is_allowed("localhost") is True
    assert debug_routes._host_is_allowed("localhost:8765") is True
    assert debug_routes._host_is_allowed("127.0.0.1") is True
    assert debug_routes._host_is_allowed("127.0.0.1:8765") is True
    assert debug_routes._host_is_allowed("[::1]") is True
    assert debug_routes._host_is_allowed("[::1]:8765") is True


def test_host_check_rejects_non_allowed():
    assert debug_routes._host_is_allowed("attacker.example.com") is False
    assert debug_routes._host_is_allowed("attacker.example.com:80") is False
    assert debug_routes._host_is_allowed("evil.com:8765") is False
    assert debug_routes._host_is_allowed("") is False


def test_host_check_case_insensitive():
    assert debug_routes._host_is_allowed("LocalHost:8765") is True
    assert debug_routes._host_is_allowed("LOCALHOST") is True


# --- /debug/state --------------------------------------------------------


def test_debug_state_returns_200_with_allowed_host(app_with_debug: FastAPI):
    with TestClient(app_with_debug) as client:
        r = client.get("/debug/state", headers={"host": "localhost:8765"})
    assert r.status_code == 200
    body = r.json()
    assert "metrics" in body or "event_journal" in body


def test_debug_state_403_on_disallowed_host(app_with_debug: FastAPI):
    with TestClient(app_with_debug) as client:
        r = client.get("/debug/state", headers={"host": "attacker.example.com"})
    assert r.status_code == 403


def test_debug_state_403_on_default_testserver_host(app_with_debug: FastAPI):
    """TestClient の既定 host=testserver は外部扱い、 403 になる (= デフォルトで漏れない構造)。"""
    with TestClient(app_with_debug) as client:
        r = client.get("/debug/state")
    assert r.status_code == 403


# --- /debug/metrics ------------------------------------------------------


def test_debug_metrics_returns_snapshot(app_with_debug: FastAPI):
    with TestClient(app_with_debug) as client:
        r = client.get("/debug/metrics", headers={"host": "127.0.0.1"})
    assert r.status_code == 200
    body = r.json()
    assert set(body.keys()) >= {"counters", "gauges", "histograms"}


def test_debug_metrics_403_on_disallowed_host(app_with_debug: FastAPI):
    with TestClient(app_with_debug) as client:
        r = client.get("/debug/metrics", headers={"host": "evil.com"})
    assert r.status_code == 403


# --- /debug/log ----------------------------------------------------------


def test_debug_log_returns_recent_entries(app_with_debug: FastAPI):
    record(sid="A", kind="sse_user_message", event={"text": "hi"})
    record(sid="B", kind="sse_assistant", event={"text": "yo"})

    with TestClient(app_with_debug) as client:
        r = client.get("/debug/log", headers={"host": "localhost"})
    assert r.status_code == 200
    body = r.json()
    assert body["count"] == 2
    assert body["returned"] == 2
    assert len(body["entries"]) == 2


def test_debug_log_filters_by_sid(app_with_debug: FastAPI):
    record(sid="A", kind="k", event={"i": 1})
    record(sid="B", kind="k", event={"i": 2})

    with TestClient(app_with_debug) as client:
        r = client.get("/debug/log?sid=A", headers={"host": "localhost"})
    body = r.json()
    assert body["count"] == 1
    assert body["entries"][0]["sid"] == "A"


def test_debug_log_limit_returns_tail(app_with_debug: FastAPI):
    for i in range(10):
        record(sid="s", kind="k", event={"i": i})
    with TestClient(app_with_debug) as client:
        r = client.get("/debug/log?limit=3", headers={"host": "localhost"})
    body = r.json()
    assert body["returned"] == 3
    # 末尾 3 件
    received = [e["event"]["i"] for e in body["entries"]]
    assert received == [7, 8, 9]


# --- /debug/replay -------------------------------------------------------


def test_debug_replay_streams_sse_frames(app_with_debug: FastAPI):
    record(sid="s", kind="k", event={"i": 1}, ts=0.0)
    record(sid="s", kind="k", event={"i": 2}, ts=1.0)

    with TestClient(app_with_debug) as client:
        with client.stream("POST", "/debug/replay", json={"speed": 0.0}, headers={"host": "localhost"}) as r:
            assert r.status_code == 200
            assert r.headers.get("content-type", "").startswith("text/event-stream")
            body = "".join(chunk for chunk in r.iter_text())

    # SSE frame が 2 個含まれる
    frames = [f for f in body.split("\n\n") if f.startswith("id:")]
    assert len(frames) == 2
    payload0 = json.loads(frames[0].split("data: ", 1)[1])
    assert payload0["event"]["i"] == 1


def test_debug_replay_403_on_disallowed_host(app_with_debug: FastAPI):
    with TestClient(app_with_debug) as client:
        r = client.post("/debug/replay", json={}, headers={"host": "attacker.example.com"})
    assert r.status_code == 403


def test_debug_replay_filter_by_sid(app_with_debug: FastAPI):
    record(sid="A", kind="k", event={"i": 1})
    record(sid="B", kind="k", event={"i": 2})

    with TestClient(app_with_debug) as client:
        with client.stream(
            "POST",
            "/debug/replay",
            json={"sid": "A", "speed": 0.0},
            headers={"host": "localhost"},
        ) as r:
            body = "".join(chunk for chunk in r.iter_text())
    frames = [f for f in body.split("\n\n") if f.startswith("id:")]
    assert len(frames) == 1
    payload = json.loads(frames[0].split("data: ", 1)[1])
    assert payload["sid"] == "A"
