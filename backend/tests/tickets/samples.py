"""The set-up the tests of the tickets share: three tabs, a place for the tickets under the test's folder, and the guard's
commands replaced by `fake_guard.py`. A test file takes the fixtures with
`from backend.tests.tickets.samples import ticket_env  # noqa: F401`.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

import backend._common.config as config_mod
from backend._common import paths
from backend._common.state import SessionDef
from backend.tickets import ticket_checks, ticket_places, ticket_service

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
