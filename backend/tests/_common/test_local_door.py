"""The doors only programs on this machine may use refuse a request `tailscale serve` handed on, which reaches the
backend from this machine's own address too (`_common/local_door.py`)."""
from __future__ import annotations

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

import backend.routes.ask as ask_routes
import backend.routes.hooks as hooks_routes
from backend._common.local_door import from_this_machine, require_this_machine

SERVED = {"X-Forwarded-Host": "machine.tailnet.example", "X-Forwarded-For": "100.64.0.7"}


def _request(host: str | None, headers: dict[str, str] | None = None) -> Request:
    scope = {"type": "http", "method": "GET", "path": "/", "headers": [
        (name.lower().encode(), value.encode()) for name, value in (headers or {}).items()]}
    if host is not None:
        scope["client"] = (host, 50000)
    return Request(scope)


@pytest.mark.parametrize("host", ["127.0.0.1", "::1", "localhost", "testclient"])
def test_a_program_on_this_machine_is_let_in(host):
    assert from_this_machine(_request(host))


@pytest.mark.parametrize("headers", [SERVED, {"X-Forwarded-Host": "machine.tailnet.example"},
                                     {"x-forwarded-for": "100.64.0.7"}])
def test_a_request_tailscale_serve_handed_on_is_not_from_this_machine(headers):
    assert not from_this_machine(_request("127.0.0.1", headers))


def test_another_address_or_none_is_not_from_this_machine():
    assert not from_this_machine(_request("100.64.0.7"))
    assert not from_this_machine(_request(None))


def test_the_refusal_carries_the_doors_code():
    with pytest.raises(Exception) as raised:
        require_this_machine(_request("127.0.0.1", SERVED), "ask_local_only")
    assert raised.value.status_code == 403 and raised.value.detail["code"] == "ask_local_only"


def test_the_ask_door_refuses_a_request_from_the_tailnet(monkeypatch):
    async def ask(*_args, **_kwargs):
        raise AssertionError("nothing may be asked")
    monkeypatch.setattr(ask_routes.ask_turn, "ask", ask)
    app = FastAPI()
    app.include_router(ask_routes.router)
    r = TestClient(app).post("/sessions/ses_head/ask", data={"text": "hello"}, headers=SERVED)
    assert r.status_code == 403 and r.json()["detail"]["code"] == "ask_local_only"


def test_the_hook_door_refuses_a_hook_from_the_tailnet():
    app = FastAPI()
    app.include_router(hooks_routes.router)
    r = TestClient(app).post("/hooks/event", json={"hook_event_name": "Stop"}, headers=SERVED)
    assert r.status_code == 403


def _tickets_client() -> TestClient:
    import backend.routes.tickets as tickets_routes
    app = FastAPI()
    app.include_router(tickets_routes.router)
    return TestClient(app)


def test_a_tabs_ticket_door_refuses_a_request_from_the_tailnet(isolated_state):
    r = _tickets_client().post("/tickets/home-261120-99/entries", data={"from": "ses_x", "text": "hi"}, headers=SERVED)
    assert r.status_code == 403 and r.json()["detail"]["code"] == "ticket_local_only"


def test_the_operators_answer_doors_take_the_screen_through_tailscale_serve(isolated_state):
    client = _tickets_client()
    for response in (client.get("/tickets/home-261120-99/answer", headers=SERVED),
                     client.post("/tickets/home-261120-99/answer/seen", headers=SERVED)):
        detail = response.json().get("detail")
        code = detail.get("code") if isinstance(detail, dict) else None
        assert code != "ticket_local_only"
