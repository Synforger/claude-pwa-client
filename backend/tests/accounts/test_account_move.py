"""What moving a tab records: where it belongs when the account fallback moved it, the record the client wrote
for that, and the client deleting that record once the tab leaves (`accounts/account_move.py`)."""
from __future__ import annotations

import backend._common.config as config
from backend.accounts.account_move import move_tab_account, remove_written_copy
from backend.fork.lineage import LineageCut
from backend.tests.fork.test_fork import _run, _setup_account_move


def _with_projects(monkeypatch, src, work_dir) -> None:
    monkeypatch.setattr(config, "CLAUDE_PROJECTS_DIRS", [src.parent.parent, work_dir.parent], raising=False)


def test_a_fallback_move_records_where_the_tab_belongs_and_the_record_the_client_wrote(
        tmp_path, monkeypatch, isolated_state):
    _sessions, tab, src, work_dir, events = _setup_account_move(tmp_path, monkeypatch, isolated_state)
    tab.account_id = "work"
    _run(move_tab_account(tab.id, "personal", fallback_from="work"))
    assert (tab.account_id, tab.fallback_from) == ("personal", "work")
    written = tmp_path / f"{tab.resume_session_id}.jsonl"
    assert tab.fallback_copy == str(written) and written.is_file()
    assert events == [f"kill {tab.id}", f"spawn {tab.id}"]


def test_a_move_by_hand_leaves_no_record_of_belonging(tmp_path, monkeypatch, isolated_state):
    _sessions, tab, _src, work_dir, _events = _setup_account_move(tmp_path, monkeypatch, isolated_state)
    _run(move_tab_account(tab.id, "work", cut=LineageCut.CLEAN_TURN))
    assert (tab.fallback_from, tab.fallback_copy) == (None, None)


def test_the_client_deletes_the_record_it_wrote_when_the_tab_leaves_the_account(tmp_path, monkeypatch, isolated_state):
    _sessions, tab, src, work_dir, _events = _setup_account_move(tmp_path, monkeypatch, isolated_state)
    _with_projects(monkeypatch, src, work_dir)
    tab.account_id = "work"
    _run(move_tab_account(tab.id, "personal", fallback_from="work"))
    copy = tab.fallback_copy
    assert copy is not None and (tmp_path / copy.rsplit("/", 1)[1]).is_file()
    _run(move_tab_account(tab.id, "work"))
    assert not (tmp_path / copy.rsplit("/", 1)[1]).exists()
    assert (tab.account_id, tab.fallback_from, tab.fallback_copy) == ("work", None, None)
    assert src.is_file()                                              # the tab's own records are never deleted


def test_only_a_record_inside_an_accounts_projects_folder_is_deleted(tmp_path, monkeypatch):
    projects = tmp_path / "projects"
    (projects / "-cwd").mkdir(parents=True)
    monkeypatch.setattr(config, "CLAUDE_PROJECTS_DIRS", [projects], raising=False)
    inside, outside, wrong_kind = projects / "-cwd" / "a.jsonl", tmp_path / "b.jsonl", projects / "-cwd" / "c.txt"
    for path in (inside, outside, wrong_kind):
        path.write_text("{}\n")
    assert [remove_written_copy(str(p)) for p in (outside, wrong_kind, inside)] == [False, False, True]
    assert outside.exists() and wrong_kind.exists() and not inside.exists()
    assert remove_written_copy(str(inside)) is False                    # already gone
