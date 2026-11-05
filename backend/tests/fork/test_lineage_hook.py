"""The command the configuration names runs once a new conversation record is written and before it is opened
(`fork/lineage_hook.py`, `fork/lineage.py`). The command is replaced by a small script here."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest
from fastapi import HTTPException

import backend._common.config as config
import backend.fork.lineage_hook as lineage_hook
from backend.accounts.account_move import move_tab_account
from backend.tests.fork.test_fork import SAMPLE, _run, _setup_account_move, _setup_fork_env


def _hook(monkeypatch, tmp_path: Path, body: str) -> Path:
    """Configure a command that runs `body` (= Python) with the filled-in words; the words go to the returned file."""
    out = tmp_path / "hook-words.json"
    script = tmp_path / "hook.py"
    script.write_text(f"import json, sys, time, pathlib\n{body}\n")
    monkeypatch.setattr(config, "LINEAGE_HOOK", [sys.executable, str(script), str(out), "{session}", "--carry-from",
                                                  "{from_session}"], raising=False)
    return out


RECORD_WORDS = "pathlib.Path(sys.argv[1]).write_text(json.dumps(sys.argv[2:]))"


def test_without_a_configured_command_nothing_is_run_and_the_conversation_opens(tmp_path, monkeypatch, isolated_state):
    monkeypatch.setattr(config, "LINEAGE_HOOK", [], raising=False)
    monkeypatch.setattr(lineage_hook.subprocess, "run", lambda *a, **k: pytest.fail("a command was run"))
    _sessions, tab, _src, _work, events = _setup_account_move(tmp_path, monkeypatch, isolated_state)
    _run(move_tab_account(tab.id, "work"))
    assert events == [f"kill {tab.id}", f"spawn {tab.id}"]


def test_the_words_of_the_command_are_filled_with_the_new_and_the_previous_conversation(
        tmp_path, monkeypatch, isolated_state):
    words = _hook(monkeypatch, tmp_path, RECORD_WORDS)
    _sessions, tab, _src, _work, _events = _setup_account_move(tmp_path, monkeypatch, isolated_state)
    _run(move_tab_account(tab.id, "work"))
    assert json.loads(words.read_text()) == [tab.resume_session_id, "--carry-from", "OLD"]


def test_when_the_command_succeeds_the_conversation_is_opened(tmp_path, monkeypatch, isolated_state):
    _hook(monkeypatch, tmp_path, RECORD_WORDS)
    _sessions, tab, _src, work_dir, events = _setup_account_move(tmp_path, monkeypatch, isolated_state)
    _run(move_tab_account(tab.id, "work"))
    assert events == [f"kill {tab.id}", f"spawn {tab.id}"]
    assert len(list(work_dir.glob("*.jsonl"))) == 1


def test_when_the_command_fails_a_move_is_refused_and_the_record_written_for_it_is_deleted(
        tmp_path, monkeypatch, isolated_state):
    _hook(monkeypatch, tmp_path, "sys.stderr.write('no marks\\n'); sys.exit(3)")
    _sessions, tab, _src, work_dir, events = _setup_account_move(tmp_path, monkeypatch, isolated_state)
    with pytest.raises(HTTPException) as refused:
        _run(move_tab_account(tab.id, "work"))
    assert refused.value.status_code == 409
    assert events == []                                      # the tab was not touched, nothing was opened
    assert (tab.account_id, tab.resume_session_id) == ("personal", None)
    assert list(work_dir.glob("*.jsonl")) == []


def test_a_command_that_does_not_finish_in_time_fails_the_same_way(tmp_path, monkeypatch, isolated_state):
    monkeypatch.setattr(lineage_hook, "LINEAGE_HOOK_TIMEOUT_SEC", 0.3)
    _hook(monkeypatch, tmp_path, "time.sleep(5)")
    _sessions, tab, _src, work_dir, events = _setup_account_move(tmp_path, monkeypatch, isolated_state)
    with pytest.raises(HTTPException) as refused:
        _run(move_tab_account(tab.id, "work"))
    assert refused.value.status_code == 409 and events == [] and list(work_dir.glob("*.jsonl")) == []


def test_a_fork_is_refused_when_the_command_fails_and_leaves_no_tab_and_no_record(
        tmp_path, monkeypatch, isolated_state):
    from backend._common.state import sessions_meta  # noqa: PLC0415
    _hook(monkeypatch, tmp_path, "sys.exit(1)")
    chat_routes, parent, src = _setup_fork_env(tmp_path, monkeypatch, isolated_state, SAMPLE)
    tabs_before = set(sessions_meta)
    with pytest.raises(HTTPException) as refused:
        _run(chat_routes.fork_session(parent.id, {"from_uuid": "u2"}))
    assert refused.value.status_code == 409
    assert set(sessions_meta) == tabs_before
    assert [p.name for p in tmp_path.glob("*.jsonl")] == [src.name]


def test_a_fork_runs_the_command_with_the_conversation_it_continues(tmp_path, monkeypatch, isolated_state):
    words = _hook(monkeypatch, tmp_path, RECORD_WORDS)
    chat_routes, parent, _src = _setup_fork_env(tmp_path, monkeypatch, isolated_state, SAMPLE)
    out = _run(chat_routes.fork_session(parent.id, {"from_uuid": "u2"}))
    assert json.loads(words.read_text()) == [out["resume_session_id"], "--carry-from", "OLD"]
