"""The set-up the tests of the tickets share: three tabs, a place for the tickets under the test's folder, and the guard's
commands replaced by `fake_guard.py`. A test file takes the fixtures with
`from backend.tests.tickets.samples import ticket_env  # noqa: F401`.
"""
from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

import backend._common.config as config_mod
from backend._common import paths
from backend._common.state import SessionDef, sessions_meta
from backend.tests.async_run import run
from backend.tickets import (answer_delivery, answer_queue, ticket_answer, ticket_checks, ticket_file, ticket_index,
                             ticket_places, ticket_return, ticket_service)
from backend.tickets.answer_queue import AnswerKey

FAKE_GUARD = Path(__file__).with_name("fake_guard.py")
#: The words of each of the guard's commands, as the configuration lists them (= the flags the guard's note names)
COMMANDS = {
    "place": ["--place-for", "{session}", "--typed-in", "{typed_in}"],
    "places": ["--places"],
    "write": ["--to-place", "{place}", "--text", "{text_file}", "--typed-in", "{typed_in}"],
    "covers": ["--to", "{session}", "--covers-place", "{place}", "--folder", "{folder}"],
    "read": ["--to", "{session}", "--text", "{text_file}"],
}
TABS = {"ses_a": "client work", "ses_b": "notes", "ses_c": "slides"}


def write_config(monkeypatch, tmp_path: Path, **values) -> None:
    """Write the configuration file and point the backend at it."""
    path = tmp_path / "config.json"
    path.write_text(json.dumps({"uploads_tmp": str(tmp_path / "uploads"), **values}))
    monkeypatch.setattr(config_mod, "CONFIG_PATH", path)
    config_mod.get_config.cache_clear()


class Guard:
    """The fake guard of one test: what it answers (`answer`), and what it was asked (`calls`)."""

    def __init__(self, monkeypatch, tmp_path: Path) -> None:
        self._monkeypatch, self._tmp = monkeypatch, tmp_path
        self.rules_file, self.log_file = tmp_path / "rules.json", tmp_path / "guard.log"
        self.rules: dict = {"log": str(self.log_file)}
        self.rules_file.write_text(json.dumps(self.rules))

    def use(self, *modes: str, **answers: dict) -> None:
        """Configure the commands of `modes` (= keys of `COMMANDS`), answering as `answers[<mode>]` says."""
        self.answer(**answers)
        keys = {f"ticket_{mode}_check": [sys.executable, str(FAKE_GUARD), mode, str(self.rules_file), *COMMANDS[mode]]
                for mode in modes}
        write_config(self._monkeypatch, self._tmp, **keys)

    def answer(self, **answers: dict) -> None:
        self.rules.update(answers)
        self.rules_file.write_text(json.dumps(self.rules))

    def calls(self, mode: str | None = None) -> list[dict]:
        if not self.log_file.exists():
            return []
        rows = [json.loads(line) for line in self.log_file.read_text().splitlines()]
        return [row for row in rows if mode in (None, row["mode"])]


@pytest.fixture
def ticket_env(isolated_state, tmp_path, monkeypatch):
    """Tabs `ses_a`, `ses_b`, `ses_c`, the tickets' place under `tmp_path`, no guard configured. Each tab's conversation
    is `conv-<tab>` to the guard."""
    monkeypatch.setattr(paths, "TICKETS_DIR", tmp_path / "state" / "tickets")
    monkeypatch.setattr(ticket_checks, "session_of", lambda tab: f"conv-{tab}")
    monkeypatch.setattr(ticket_service, "last_operator_text", lambda record: "please fix the title")
    ticket_places.forget_all()
    write_config(monkeypatch, tmp_path, machine_name="home")
    for tab, title in TABS.items():
        isolated_state.sessions_meta[tab] = SessionDef(id=tab, agent_id="agent_a", title=title, created_at=0, tier="projects/AP")
    yield SimpleNamespace(root=tmp_path, guard=Guard(monkeypatch, tmp_path), tickets=tmp_path / "state" / "tickets")
    ticket_places.forget_all()


def refusal(status: int, code: str) -> HTTPException:
    """The error a door of the backend raises."""
    return HTTPException(status, detail={"code": code, "message": code})


@pytest.fixture
def delivery_env(ticket_env, monkeypatch):
    """`ticket_env` and stand-ins for the claude of each tab: what was typed into which tab (`typed`), which tabs are working
    (`busy`), were asked to close (`close_asked`), cannot be reached (`unreachable`) or are stopped by the account hold
    (`kept`), what typing into a tab fails with (`fail`), the clock of the delivery in seconds (`clock`), the answers
    started in the background (`started`), the children whose memo was set back to working (`handed`) and the tabs of the backend (`tabs`, to close one)."""
    env = SimpleNamespace(**vars(ticket_env), typed=[], busy=set(), close_asked=set(), unreachable=set(), kept=set(), fail={},
                          clock=[1000.0], started=[], handed=[], tabs=sessions_meta)

    async def deliver_or_keep(tab_id, text):
        await asyncio.sleep(0)
        if tab_id in env.fail:
            raise env.fail[tab_id]
        env.typed.append((tab_id, text))
        return {"ok": True, "kept": True} if tab_id in env.kept else {"ok": True}

    async def hand_over_work(sender, receiver):
        env.handed.append((sender, receiver))

    monkeypatch.setattr(answer_delivery, "deliver_or_keep", deliver_or_keep)
    monkeypatch.setattr(ticket_return, "deliver_or_keep", deliver_or_keep)
    monkeypatch.setattr(ticket_return, "hand_over_work", hand_over_work)
    monkeypatch.setattr(answer_delivery, "tab_reachable", lambda tab_id: tab_id not in env.unreachable)
    monkeypatch.setattr(answer_delivery, "is_busy", lambda tab_id: tab_id in env.busy)
    monkeypatch.setattr(answer_delivery, "jsonl_path_for_session", lambda tab_id: Path(f"/records/{tab_id}.jsonl"))
    monkeypatch.setattr(answer_delivery.rollover, "asked", lambda record: record.stem in env.close_asked)
    monkeypatch.setattr(answer_delivery, "time", SimpleNamespace(monotonic=lambda: env.clock[0]))
    monkeypatch.setattr(answer_delivery, "start_delivery", env.started.append)
    for state in (answer_delivery._locks, answer_delivery._retry_after, answer_delivery._last_waiting):
        state.clear()
    monkeypatch.setattr(answer_delivery, "_quiet_until", 0.0)
    yield env
    for state in (answer_delivery._locks, answer_delivery._retry_after, answer_delivery._last_waiting):
        state.clear()


def waiting_ticket(*, recommend: str | None = "A", holder: str = "ses_a") -> str:
    """A ticket opened by `ses_a`, held by `holder` and waiting for the operator's answer to a question."""
    ticket = run(ticket_service.open_ticket("ses_a", "Title", "Request", operator_said=False))["id"]
    if holder != "ses_a":
        ticket_index.put(ticket, ticket_index.get(ticket)._replace(holder=holder))
    run(ticket_service.ask("ses_a", ticket, "decide", "A or B?", recommend))
    return ticket


def asked_at_of(folder: Path, ticket: str) -> str:
    """The time of the last `asked` line of the ticket (= what the screen sends back with the answer)."""
    return [entry for entry in ticket_file.read(folder, ticket) if entry["kind"] == "asked"][-1]["at"]


def answered_ticket(env, *, text: str = "Take B", holder: str = "ses_a") -> AnswerKey:
    """A ticket held by `holder` that the operator answered with `text`: its answer is in the queue, not yet delivered."""
    ticket = waiting_ticket(holder=holder)
    asked_at = asked_at_of(env.tickets, ticket)
    run(ticket_answer.answer(ticket, asked_at, text, False))
    return AnswerKey(ticket, asked_at)


def queued() -> list[AnswerKey]:
    return answer_queue.keys()
