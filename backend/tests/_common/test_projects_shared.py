"""Whether two accounts keep their conversation records in one folder (`_common/config.py`): judged by the folder
itself, so a link and its target are one folder however the accounts name it."""
from __future__ import annotations

import pytest

import backend._common.config as config
from backend._common.state import SleepMark, SessionDef
from backend.tests.limit_samples import use_accounts


def _accounts(tmp_path, monkeypatch, *, linked: bool, names=("personal", "work")) -> dict:
    """`personal` keeps its records in `<home>/.claude/projects`, `work` in `<tmp>/work/projects`, a link to it when
    `linked`. Both folders exist."""
    home = tmp_path / "home"
    (home / ".claude" / "projects").mkdir(parents=True)
    (tmp_path / "work").mkdir()
    if linked:
        (tmp_path / "work" / "projects").symlink_to(home / ".claude" / "projects")
    else:
        (tmp_path / "work" / "projects").mkdir()
    monkeypatch.setenv("HOME", str(home))
    accounts = {"personal": {"display_name": "Personal", "env": {}},
                "work": {"display_name": "Work", "env": {"CLAUDE_CONFIG_DIR": str(tmp_path / "work")}}}
    use_accounts(monkeypatch, accounts)
    return accounts


def test_accounts_whose_projects_folder_is_a_link_to_the_other_share_their_records(tmp_path, monkeypatch):
    _accounts(tmp_path, monkeypatch, linked=True)
    assert config.projects_shared("personal", "work") and config.projects_shared("work", "personal")
    assert config.projects_shared(None, "work")                        # a tab with no account is on the default one


def test_accounts_with_folders_of_their_own_do_not(tmp_path, monkeypatch):
    _accounts(tmp_path, monkeypatch, linked=False)
    assert not config.projects_shared("personal", "work")


def test_a_folder_that_does_not_exist_is_not_shared(tmp_path, monkeypatch):
    _accounts(tmp_path, monkeypatch, linked=True)
    (tmp_path / "work" / "projects").unlink()
    assert not config.projects_shared("personal", "work")


def test_an_account_the_configuration_does_not_know_shares_nothing(tmp_path, monkeypatch):
    _accounts(tmp_path, monkeypatch, linked=True)
    assert not config.projects_shared("personal", "ghost")


@pytest.mark.parametrize("linked, listed", [(True, 1), (False, 2)])
def test_a_folder_two_accounts_share_is_listed_once(tmp_path, monkeypatch, linked, listed):
    _accounts(tmp_path, monkeypatch, linked=linked)
    assert len(config.CLAUDE_PROJECTS_DIRS) == listed


def test_the_accounts_of_a_folder_are_found_by_the_folder_whichever_way_it_is_named(tmp_path, monkeypatch):
    _accounts(tmp_path, monkeypatch, linked=True)
    assert config.accounts_sharing(tmp_path / "work" / "projects") == ["personal", "work"]
    assert config.accounts_sharing(tmp_path / "home" / ".claude" / "projects") == ["personal", "work"]
    assert config.accounts_sharing(tmp_path / "elsewhere") == []


def _sleeping_tab(account: str) -> SessionDef:
    tab = SessionDef(id="ses_a", agent_id="agent", title="t", created_at=0, account_id=account)
    tab.sleep = SleepMark(claude_sid="abc", record="/x/abc.jsonl", slept_at=1, account_id="personal")
    return tab


@pytest.mark.parametrize("linked, reopens", [(True, "abc"), (False, None)])
def test_a_sleeping_tab_reopens_its_conversation_under_another_account_only_when_the_records_are_shared(
        tmp_path, monkeypatch, linked, reopens):
    _accounts(tmp_path, monkeypatch, linked=linked)
    assert _sleeping_tab("work").sleeping_claude_sid() == reopens
    assert _sleeping_tab("personal").sleeping_claude_sid() == "abc"
