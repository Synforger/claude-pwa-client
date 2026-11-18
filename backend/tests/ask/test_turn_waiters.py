"""The hooks end the wait of an ask: `Stop` hands over the answer, `SessionStart` says the cleared conversation opened
(`backend/ask/turn_waiters.py`, `routes/hooks.py`)."""
from __future__ import annotations

import asyncio

import httpx2
import pytest
from fastapi import FastAPI

import backend.routes.hooks as hooks_router
from backend.ask import turn_waiters
from backend.tests.async_run import run
from backend.tests.routes.test_hooks_router import (  # noqa: F401  (= fixtures of the hooks' own tests)
    captured_pushes, fake_agents, fake_bindings,
)


@pytest.fixture(autouse=True)
def no_waiters(monkeypatch):
    monkeypatch.setattr(turn_waiters, "_waiters", {})


def test_one_wait_per_tab_and_only_its_owner_ends_it():
    first = turn_waiters.start_waiting("ses_a")
    assert first is not None and turn_waiters.start_waiting("ses_a") is None
    turn_waiters.stop_waiting("ses_a", turn_waiters.TurnWaiter())      # another wait's end leaves this one
    assert turn_waiters.start_waiting("ses_a") is None
    turn_waiters.stop_waiting("ses_a", first)
    assert turn_waiters.start_waiting("ses_a") is not None


def test_a_stop_before_the_answer_is_expected_is_not_taken_for_it():
    async def scenario() -> str:
        waiter = turn_waiters.start_waiting("ses_a")
        turn_waiters.turn_ended("ses_a", "the turn of a /clear")
        answer = turn_waiters.expect_answer(waiter)
        turn_waiters.turn_ended("ses_a", "the answer")
        turn_waiters.turn_ended("ses_a", "a later turn")
        return await asyncio.wait_for(answer, 1)
    assert run(scenario()) == "the answer"


def test_hooks_of_a_tab_with_no_ask_change_nothing():
    turn_waiters.turn_ended("ses_none", "text")
    turn_waiters.conversation_opened("ses_none")
    assert turn_waiters._waiters == {}


def test_the_stop_hook_hands_its_last_message_to_the_waiting_ask(fake_agents, fake_bindings, captured_pushes):
    fake_bindings("primary", "claude-internal-uuid")
    app = FastAPI()
    app.include_router(hooks_router.router)

    async def scenario() -> str:
        # the hook is served on the same loop as the wait, as in the backend
        waiter = turn_waiters.start_waiting("primary")
        answer = turn_waiters.expect_answer(waiter)
        payload = {"hook_event_name": "Stop", "session_id": "claude-internal-uuid", "cwd": fake_agents["cwd"],
                   "last_assistant_message": "The tavern is quiet."}
        async with httpx2.AsyncClient(transport=httpx2.ASGITransport(app=app), base_url="http://backend") as client:
            assert (await client.post("/hooks/event", json=payload)).status_code == 200
        return await asyncio.wait_for(answer, 1)
    assert run(scenario()) == "The tavern is quiet."
