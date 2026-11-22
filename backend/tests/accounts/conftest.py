"""Two accounts that keep their conversation records in one folder: `work`'s `projects` is a link to `personal`'s. A tab
on `personal` has its record there; the stop and the start of its claude are recorded, and nothing else of the move is
replaced."""
from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

import backend._common.config as config
import backend.accounts.tab_restart as tab_restart
import backend.fork.lineage as lineage
import backend.jsonl.jsonl_watcher as jsonl_watcher
import backend.terminal.routes as pty_routes
import backend.terminal.runner as pty_runner
from backend.tests.fork.test_fork import SAMPLE
from backend.tests.limit_samples import use_accounts

CWD = "/work/cwd"
CLAUDE_ID = "OLD"


def write_record(path, lines: list[str], *, whole_line_end: bool = True) -> None:
    """The record, one row to a line; `whole_line_end` False leaves the last line without its newline."""
    path.write_text("\n".join(lines) + ("\n" if whole_line_end else ""), encoding="utf-8")


def uuids_of(path) -> list[str]:
    return [json.loads(raw)["uuid"] for raw in path.read_text(encoding="utf-8").splitlines()
            if raw.strip() and "uuid" in json.loads(raw)]


@pytest.fixture
def shared(tmp_path, monkeypatch, isolated_state):
    """`shared.tab` is on `personal` with its record `shared.record` in the folder both accounts open; `shared.folder`
    is that folder under `projects`, `shared.events` the stops and starts of the tab's claude, `shared.ended` what was
    recorded of the conversations that ended."""
    home = tmp_path / "home"
    projects = home / ".claude" / "projects"
    folder = projects / config.cwd_to_project_dirname(CWD)
    folder.mkdir(parents=True)
    (tmp_path / "work").mkdir()
    (tmp_path / "work" / "projects").symlink_to(projects)
    monkeypatch.setenv("HOME", str(home))
    use_accounts(monkeypatch, {
        "personal": {"display_name": "Personal", "env": {}},
        "work": {"display_name": "Work", "env": {"CLAUDE_CONFIG_DIR": str(tmp_path / "work")}},
    })
    agent_id = next(iter(config.AGENTS))
    monkeypatch.setattr(config, "AGENTS", {agent_id: {"cwd": CWD}})
    tab = isolated_state.register_session(agent_id, title="Chat")
    tab.account_id = "personal"
    record = folder / f"{CLAUDE_ID}.jsonl"
    write_record(record, SAMPLE)
    monkeypatch.setattr(pty_runner, "jsonl_path_for_session", lambda _sid: record)
    monkeypatch.setattr(jsonl_watcher, "get_jsonl_for", lambda _sid: record)
    events: list[str] = []
    ended: list[tuple[str, str]] = []

    async def stop(sid):
        events.append(f"kill {sid}")
        return True

    async def spawn(sid, **_kwargs):
        events.append(f"spawn {sid}")
    monkeypatch.setattr(tab_restart, "stop_tab", stop)
    monkeypatch.setattr(pty_routes, "ensure_pty_session_for", spawn)
    monkeypatch.setattr(tab_restart.session_history, "record_end",
                        lambda sid, claude_sid, jsonl_path=None: ended.append((sid, jsonl_path)))
    monkeypatch.setattr(tab_restart.jsonl_watcher, "unregister", lambda _sid: None)
    monkeypatch.setattr(lineage, "carry_over", lambda *_args: None)
    return SimpleNamespace(tab=tab, record=record, folder=folder, projects=projects, events=events, ended=ended,
                           home=home, work_projects=tmp_path / "work" / "projects", tmp_path=tmp_path)
