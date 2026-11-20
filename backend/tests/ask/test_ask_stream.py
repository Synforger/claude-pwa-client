"""An ask that hands on the answer while the turn runs (`ask_turn.ask_stream`, `POST /sessions/{id}/ask` with
`stream`). The tab, the hooks and the screen are made up: the screen is read as often as the test says, and the turn
ends when the test says."""
from __future__ import annotations

import asyncio
import json

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

import backend.routes.ask as ask_routes
from backend._common.errors import raise_error
from backend.ask import ask_turn, screen_watch, turn_waiters
from backend.tests.ask.conftest import NAME, TAB
from backend.tests.async_run import run

QUESTION = "Describe the tavern."


def _screen(answer: str | None) -> screen_watch.PaneScreen | None:
    if answer is None:
        return None
    return screen_watch.PaneScreen(120, f"❯ {QUESTION}\n\n⏺ {answer}\n✻ Doing… (1s · ↓ 3 tokens)\n──")


@pytest.fixture
def screens(monkeypatch):
    """The screens the tab shows, one per read, the last one from then on."""
    shown: list[str | None] = []

    def read(session_id: str):
        return _screen(shown.pop(0) if len(shown) > 1 else shown[0])
    monkeypatch.setattr(screen_watch, "POLL_SEC", 0.01)
    monkeypatch.setattr(screen_watch, "read_screen", read)
    return shown


async def _collect(events, end_turn_after: int | None = None) -> list[dict]:
    """The events to the end; the turn ends (= its `Stop` hook) once `end_turn_after` partials have come."""
    seen: list[dict] = []
    async for event in events:
        seen.append(event)
        if end_turn_after is not None and sum(e["type"] == "partial" for e in seen) == end_turn_after:
            turn_waiters.turn_ended(TAB, "The tavern is quiet.", "claude-uuid")
    return seen


def test_the_stream_gives_each_new_state_of_the_screen_then_the_answer_with_its_conversation(head, screens):
    head.answers = False
    screens.extend(["The", "The", "The tavern", "The tavern", "The tavern is q"])

    async def scenario() -> list[dict]:
        return await _collect(await ask_turn.ask_stream(NAME, QUESTION), end_turn_after=3)
    assert run(scenario()) == [
        {"type": "partial", "text": "The"},
        {"type": "partial", "text": "The tavern"},
        {"type": "partial", "text": "The tavern is q"},
        {"type": "final", "text": "The tavern is quiet.", "session": "claude-uuid"},
    ]
    assert head.typed == [(QUESTION, False)] and turn_waiters._waiters == {}


def test_a_screen_that_cannot_be_read_gives_the_answer_alone(head, screens):
    screens.append(None)

    async def scenario() -> list[dict]:
        return await _collect(await ask_turn.ask_stream(TAB, QUESTION))
    assert run(scenario()) == [{"type": "final", "text": "the answer", "session": None}]


def test_a_turn_that_does_not_end_in_time_is_the_last_event_and_is_stopped(head, screens):
    head.answers = False
    screens.append("The")

    async def scenario() -> list[dict]:
        return await _collect(await ask_turn.ask_stream(TAB, QUESTION, timeout_sec=0.1))
    events = run(scenario())
    assert events[0] == {"type": "partial", "text": "The"}
    assert events[-1]["type"] == "error" and events[-1]["code"] == "ask_timeout" and "message" in events[-1]
    assert head.keys == ["Escape"] and turn_waiters._waiters == {}


def test_a_failure_before_the_typing_is_an_error_of_the_call_and_not_an_event(head, screens):
    head.busy = True
    with pytest.raises(HTTPException) as caught:
        run(ask_turn.ask_stream(TAB, QUESTION))
    assert (caught.value.status_code, caught.value.detail["code"]) == (409, "ask_tab_busy")
    assert head.typed == [] and turn_waiters._waiters == {}


def test_a_stream_closed_early_gives_the_wait_up(head, screens):
    head.answers = False
    screens.append("The")

    async def scenario() -> None:
        events = await ask_turn.ask_stream(TAB, QUESTION)
        assert (await events.__anext__())["type"] == "partial"
        await events.aclose()
        await asyncio.sleep(0.05)
    run(scenario())
    assert turn_waiters._waiters == {}


def test_a_stream_nobody_reads_still_ends_its_wait_with_the_turn(head, screens):
    screens.append("The")

    async def scenario() -> None:
        await ask_turn.ask_stream(TAB, QUESTION)
        await asyncio.sleep(0.1)
    run(scenario())
    assert turn_waiters._waiters == {}


def _client(monkeypatch, events=None, refusal=None):
    async def ask_stream(to, text, *, fresh, timeout_sec):
        if refusal is not None:
            raise_error(*refusal)

        async def lines():
            for event in events:
                yield event
        return lines()
    monkeypatch.setattr(ask_routes.ask_turn, "ask_stream", ask_stream)
    app = FastAPI()
    app.include_router(ask_routes.router)
    return TestClient(app)


def test_the_door_streams_one_json_line_per_event(monkeypatch):
    events = [{"type": "partial", "text": "The 港"}, {"type": "final", "text": "The 港町", "session": "claude-uuid"}]
    r = _client(monkeypatch, events).post("/sessions/ses_head/ask", data={"text": "hi", "stream": "true"})
    assert r.status_code == 200 and r.headers["content-type"].startswith("application/x-ndjson")
    assert [json.loads(line) for line in r.text.splitlines()] == events
    assert "港" in r.text                                              # the characters go out as they are


def test_the_door_answers_a_failure_before_the_typing_as_an_http_error(monkeypatch):
    r = _client(monkeypatch, refusal=(409, "ask_tab_busy", "busy")).post(
        "/sessions/ses_head/ask", data={"text": "hi", "stream": "true"})
    assert (r.status_code, r.json()["detail"]["code"]) == (409, "ask_tab_busy")
