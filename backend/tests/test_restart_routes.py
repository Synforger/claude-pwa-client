"""/backend/restartable と /backend/restart (= PWA の設定メニューからの backend 再起動)。

再起動は launchd に `kickstart -k` を頼む形なので、 test では `_kickstart` を差し替えて
「何を頼んだか」 だけを見る (= 本物の launchctl は叩かない)。
"""
from __future__ import annotations

import os
import time

import pytest
from fastapi import FastAPI
from starlette.testclient import TestClient

from backend.routes import restart as restart_routes

LABEL = "com.example.pwa-backend"


@pytest.fixture
def kicked(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    calls: list[str] = []
    monkeypatch.setattr(restart_routes, "_kickstart", calls.append)
    monkeypatch.setattr(restart_routes, "_RESTART_DELAY_SEC", 0)
    monkeypatch.setattr(restart_routes.shutil, "which", lambda name: f"/bin/{name}")
    return calls


@pytest.fixture
def client() -> TestClient:
    app = FastAPI()
    app.include_router(restart_routes.router)
    return TestClient(app)


def _as_launchd_job(monkeypatch: pytest.MonkeyPatch, label: str = LABEL) -> None:
    monkeypatch.setenv("XPC_SERVICE_NAME", label)


# --- launchd の job かどうか ---------------------------------------------------


@pytest.mark.parametrize("value", ["0", "application.com.apple.Terminal.1234", ""])
def test_a_process_started_from_a_terminal_or_app_is_not_a_launchd_job(monkeypatch, kicked, value):
    monkeypatch.setenv("XPC_SERVICE_NAME", value)
    assert restart_routes.launchd_label() is None


def test_no_service_name_is_not_a_launchd_job(monkeypatch, kicked):
    monkeypatch.delenv("XPC_SERVICE_NAME", raising=False)
    assert restart_routes.launchd_label() is None


def test_a_launchd_job_is_named_by_its_label(monkeypatch, kicked):
    _as_launchd_job(monkeypatch)
    assert restart_routes.launchd_label() == LABEL


def test_without_launchctl_there_is_nothing_to_ask(monkeypatch, kicked):
    _as_launchd_job(monkeypatch)
    monkeypatch.setattr(restart_routes.shutil, "which", lambda name: None)
    assert restart_routes.launchd_label() is None


def test_restartable_answers_what_the_menu_shows(monkeypatch, kicked, client):
    monkeypatch.setenv("XPC_SERVICE_NAME", "0")
    assert client.get("/backend/restartable").json() == {"restartable": False}
    _as_launchd_job(monkeypatch)
    assert client.get("/backend/restartable").json() == {"restartable": True}


# --- 再起動の要求 ----------------------------------------------------------------


def _wait_for(calls: list[str]) -> None:
    deadline = time.monotonic() + 2
    while not calls and time.monotonic() < deadline:
        time.sleep(0.01)


def test_restart_asks_launchd_to_kickstart_this_job(monkeypatch, kicked):
    _as_launchd_job(monkeypatch)
    app = FastAPI()
    app.include_router(restart_routes.router)
    with TestClient(app) as c:
        r = c.post("/backend/restart", json={"confirm": True})
        assert r.status_code == 202
        _wait_for(kicked)
    assert kicked == [LABEL]


def test_a_backend_launchd_does_not_run_is_not_stopped(monkeypatch, kicked, client):
    monkeypatch.setenv("XPC_SERVICE_NAME", "0")
    r = client.post("/backend/restart", json={"confirm": True})
    assert r.status_code == 409
    assert kicked == []


@pytest.mark.parametrize("kwargs", [
    {},                                                                 # 本文なし
    {"content": b'{"confirm": true}', "headers": {"Content-Type": "text/plain"}},  # 別サイトの form が送れる形
])
def test_a_request_a_page_could_send_without_preflight_is_refused(monkeypatch, kicked, client, kwargs):
    _as_launchd_job(monkeypatch)
    r = client.post("/backend/restart", **kwargs)
    assert r.status_code == 422
    assert kicked == []


def test_confirm_false_restarts_nothing(monkeypatch, kicked, client):
    _as_launchd_job(monkeypatch)
    assert client.post("/backend/restart", json={"confirm": False}).status_code == 400
    assert kicked == []


def test_kickstart_targets_this_users_launchd_domain(monkeypatch):
    seen: dict = {}

    def fake_popen(argv, **kw):
        seen["argv"] = argv
        seen["new_session"] = kw.get("start_new_session")

    monkeypatch.setattr(restart_routes.subprocess, "Popen", fake_popen)
    restart_routes._kickstart(LABEL)
    assert seen["argv"] == ["launchctl", "kickstart", "-k", f"gui/{os.getuid()}/{LABEL}"]
    assert seen["new_session"] is True
