"""An ask that opens another conversation first: `resume` types `/resume <id>`, `fork` then `/branch`, each waiting for
the `SessionStart` of the conversation it opens (`ask_turn.ask` and `ask_stream`, `POST /sessions/{id}/ask`)."""
from __future__ import annotations

from pathlib import Path

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

import backend.routes.ask as ask_routes
from backend.ask import ask_turn, screen_watch, turn_waiters
from backend.tests.ask.conftest import TAB
from backend.tests.async_run import run

SAVED = "7565f8b3-672d-46fe-8ad7-7f22afeae9d5"
QUESTION = "Where did we leave off?"


def _refusal(coroutine) -> tuple[int, str]:
    with pytest.raises(HTTPException) as caught:
        run(coroutine)
    return caught.value.status_code, caught.value.detail["code"]


@pytest.fixture(autouse=True)
def quick(monkeypatch):
    monkeypatch.setattr(ask_turn, "RESUME_WAIT_SEC", 0.05)
    monkeypatch.setattr(screen_watch, "read_screen", lambda session_id: None)


def test_resume_opens_the_conversation_before_the_question_and_the_answer_names_its_conversation(head):
    head.claude_session = SAVED
    answered = run(ask_turn.ask(TAB, QUESTION, resume=SAVED))
    assert answered == {"ok": True, "id": TAB, "answer": "the answer", "session": SAVED}
    assert head.typed == [(f"/resume {SAVED}", None), (QUESTION, False)]
    assert turn_waiters._waiters == {}


def test_fork_goes_on_into_a_branch_and_the_answer_names_the_branch(head):
    head.claude_session = "branch-uuid"
    answered = run(ask_turn.ask(TAB, QUESTION, resume=SAVED, fork=True))
    assert answered["session"] == "branch-uuid"
    assert head.typed == [(f"/resume {SAVED}", None), ("/branch", None), (QUESTION, False)]


def test_a_tab_in_that_conversation_already_is_not_told_to_resume_it(head, monkeypatch):
    monkeypatch.setattr(ask_turn, "_conversation_of", lambda session_id: SAVED)
    run(ask_turn.ask(TAB, QUESTION, resume=SAVED))
    assert head.typed == [(QUESTION, False)]
    run(ask_turn.ask(TAB, QUESTION, resume=SAVED, fork=True))
    assert head.typed[1:] == [("/branch", None), (QUESTION, False)]


@pytest.mark.parametrize("opened_as", [None, "another-uuid"])
def test_a_conversation_that_does_not_open_ends_the_ask_with_one_escape_and_nothing_asked(head, opened_as):
    head.opens = opened_as is not None
    head.opened_as = opened_as
    assert _refusal(ask_turn.ask(TAB, QUESTION, resume=SAVED)) == (409, "ask_not_ready")
    assert head.typed == [(f"/resume {SAVED}", None)] and head.keys == ["Escape"] and turn_waiters._waiters == {}


def test_a_branch_that_does_not_open_ends_the_ask_the_same_way(head):
    head.branch_id = SAVED                                      # a SessionStart of the conversation it came from
    assert _refusal(ask_turn.ask(TAB, QUESTION, resume=SAVED, fork=True)) == (409, "ask_not_ready")
    assert head.typed == [(f"/resume {SAVED}", None), ("/branch", None)] and head.keys == ["Escape"]


def test_a_tab_with_no_claude_cannot_open_a_conversation(head):
    head.running = False
    assert _refusal(ask_turn.ask(TAB, QUESTION, resume=SAVED)) == (409, "ask_not_ready")
    assert head.typed == [] and head.keys == [] and turn_waiters._waiters == {}


def test_the_stream_opens_the_conversation_too_and_ends_with_its_id(head):
    head.claude_session = "branch-uuid"

    async def scenario() -> list[dict]:
        return [event async for event in await ask_turn.ask_stream(TAB, QUESTION, resume=SAVED, fork=True)]
    assert run(scenario()) == [{"type": "final", "text": "the answer", "session": "branch-uuid"}]
    assert head.typed == [(f"/resume {SAVED}", None), ("/branch", None), (QUESTION, False)]


@pytest.fixture
def door(monkeypatch):
    calls: list[tuple] = []

    async def ask(to, text, *, fresh, timeout_sec, resume=None, fork=False):
        calls.append(("ask", to, fresh, resume, fork))
        return {"ok": True, "id": "ses_head", "answer": "the answer", "session": resume}

    async def ask_stream(to, text, *, fresh, timeout_sec, resume=None, fork=False):
        calls.append(("stream", to, fresh, resume, fork))

        async def events():
            yield {"type": "final", "text": "the answer", "session": resume}
        return events()
    monkeypatch.setattr(ask_routes.ask_turn, "ask", ask)
    monkeypatch.setattr(ask_routes.ask_turn, "ask_stream", ask_stream)
    app = FastAPI()
    app.include_router(ask_routes.router)
    return TestClient(app), calls


def test_the_door_hands_resume_and_fork_to_the_ask_and_to_the_stream(door):
    client, calls = door
    assert client.post("/sessions/ses_head/ask", data={"text": "hi", "resume": SAVED.upper(), "fork": "true"}
                       ).json()["session"] == SAVED                      # the id is read in lower case
    client.post("/sessions/ses_head/ask", data={"text": "hi", "resume": SAVED, "stream": "true"})
    client.post("/sessions/ses_head/ask", data={"text": "hi"})
    assert calls == [("ask", "ses_head", False, SAVED, True), ("stream", "ses_head", False, SAVED, False),
                     ("ask", "ses_head", False, None, False)]


@pytest.mark.parametrize("form", [
    {"resume": SAVED, "fresh": "true"},
    {"fork": "true"},
    {"resume": "latest"},
    {"resume": SAVED[:-1]},
    {"resume": "../" + SAVED},
])
def test_arguments_that_do_not_go_together_are_refused_before_anything_is_typed(door, form):
    client, calls = door
    r = client.post("/sessions/ses_head/ask", data={"text": "hi", **form})
    assert (r.status_code, r.json()["detail"]["code"]) == (400, "ask_bad_args")
    assert calls == []


def test_the_conversation_a_tab_is_in_is_the_name_of_its_record(monkeypatch):
    monkeypatch.setattr(ask_turn.jsonl_watcher, "get_jsonl_for", lambda session_id: Path(f"/records/{SAVED}.jsonl"))
    assert ask_turn._conversation_of(TAB) == SAVED
    monkeypatch.setattr(ask_turn.jsonl_watcher, "get_jsonl_for", lambda session_id: None)
    assert ask_turn._conversation_of(TAB) is None
