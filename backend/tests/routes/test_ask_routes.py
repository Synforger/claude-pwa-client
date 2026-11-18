"""The door of the asks reads the form and checks its values before anything is typed (`routes/ask.py`)."""
from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import backend.routes.ask as ask_routes


@pytest.fixture
def asked(monkeypatch):
    calls: list[tuple] = []

    async def ask(to, text, *, fresh, timeout_sec):
        calls.append((to, text, fresh, timeout_sec))
        return {"ok": True, "id": "ses_head", "answer": "the answer"}
    monkeypatch.setattr(ask_routes.ask_turn, "ask", ask)
    app = FastAPI()
    app.include_router(ask_routes.router)
    return TestClient(app), calls


def test_the_form_reaches_the_ask_with_its_defaults(asked):
    client, calls = asked
    r = client.post("/sessions/Talemate の頭/ask", data={"text": "Describe the tavern."})
    assert r.json() == {"ok": True, "id": "ses_head", "answer": "the answer"}
    assert calls == [("Talemate の頭", "Describe the tavern.", False, 180.0)]


def test_fresh_and_the_wait_are_read_from_the_form(asked):
    client, calls = asked
    client.post("/sessions/ses_head/ask", data={"text": "hello", "fresh": "true", "timeout_sec": "30"})
    assert calls == [("ses_head", "hello", True, 30.0)]


@pytest.mark.parametrize(("form", "code"), [
    ({"text": "  \n"}, "ask_empty"),
    ({"text": "hello", "timeout_sec": "0"}, "ask_bad_timeout"),
    ({"text": "hello", "timeout_sec": "3601"}, "ask_bad_timeout"),
])
def test_bad_values_are_refused_before_anything_is_typed(asked, form, code):
    client, calls = asked
    r = client.post("/sessions/ses_head/ask", data=form)
    assert (r.status_code, r.json()["detail"]["code"]) == (400, code)
    assert calls == []
