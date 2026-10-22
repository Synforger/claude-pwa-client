"""The move of the memos an earlier version kept in one folder (`terminal/memo_migration.py`)."""
from __future__ import annotations

import pytest

from backend.terminal import tab_tier
from backend.terminal.memo_migration import migrate_memos
from backend.terminal.tab_memo import memo_path


@pytest.fixture
def tab(agent_folder, isolated_state, monkeypatch):
    monkeypatch.setattr(isolated_state, "save_sessions_meta", lambda: None)
    monkeypatch.setattr(tab_tier, "_tiers", {})
    return isolated_state.register_session("agent_a", title="A")


@pytest.fixture
def legacy(tmp_path):
    folder = tmp_path / "legacy-notes"
    folder.mkdir()
    return folder


def test_a_plain_file_goes_to_the_place_of_the_tab(tab, legacy, agent_folder):
    (legacy / f"{tab.id}.md").write_text("メモ\n", encoding="utf-8")
    records = migrate_memos(legacy)
    assert memo_path(tab.id).read_text(encoding="utf-8") == "メモ\n"
    assert memo_path(tab.id) == agent_folder / "pages" / tab.id / "memo.md"
    assert records == [f"memo moved: {legacy / f'{tab.id}.md'} -> {memo_path(tab.id)}"]
    assert not legacy.exists()


def test_a_plain_file_follows_the_tier_the_tab_was_started_in(tab, legacy, agent_folder, monkeypatch):
    (agent_folder / "projects" / "alpha").mkdir(parents=True)
    monkeypatch.setitem(tab_tier._tiers, tab.id, "projects/alpha")
    (legacy / f"{tab.id}.md").write_text("x", encoding="utf-8")
    migrate_memos(legacy)
    assert (agent_folder / "projects" / "alpha" / "pages" / tab.id / "memo.md").read_text(encoding="utf-8") == "x"


def test_a_link_into_a_tier_folder_keeps_the_memo_in_that_folder(tab, legacy, agent_folder):
    """The launcher of earlier versions linked each tab's memo to `<tier folder>/notes/<tab id>.md`."""
    kept = agent_folder / "projects" / "alpha" / "notes" / f"{tab.id}.md"
    kept.parent.mkdir(parents=True)
    kept.write_text("続き\n", encoding="utf-8")
    (legacy / f"{tab.id}.md").symlink_to(kept)
    migrate_memos(legacy)
    moved = agent_folder / "projects" / "alpha" / "pages" / tab.id / "memo.md"
    assert moved.read_text(encoding="utf-8") == "続き\n"
    assert not kept.exists()
    assert not (legacy / f"{tab.id}.md").exists()


def test_a_link_to_nothing_is_dropped(tab, legacy, agent_folder):
    (legacy / f"{tab.id}.md").symlink_to(agent_folder / "notes" / f"{tab.id}.md")
    assert migrate_memos(legacy) == []
    assert not (legacy / f"{tab.id}.md").is_symlink()
    assert not memo_path(tab.id).exists()


def test_a_memo_already_in_place_is_left_and_recorded(tab, legacy):
    memo_path(tab.id).parent.mkdir(parents=True)
    memo_path(tab.id).write_text("新しい方\n", encoding="utf-8")
    (legacy / f"{tab.id}.md").write_text("古い方\n", encoding="utf-8")
    records = migrate_memos(legacy)
    assert memo_path(tab.id).read_text(encoding="utf-8") == "新しい方\n"
    assert (legacy / f"{tab.id}.md").read_text(encoding="utf-8") == "古い方\n"
    assert records == [f"memo left in place (= {memo_path(tab.id)} already exists): {legacy / f'{tab.id}.md'}"]


def test_a_memo_of_a_tab_that_is_gone_is_not_touched(legacy):
    (legacy / "ses_gone.md").write_text("x", encoding="utf-8")
    assert migrate_memos(legacy) == []
    assert (legacy / "ses_gone.md").is_file()


def test_a_second_start_finds_nothing_to_move(tab, legacy):
    (legacy / f"{tab.id}.md").write_text("x", encoding="utf-8")
    assert len(migrate_memos(legacy)) == 1
    assert migrate_memos(legacy) == []
    assert memo_path(tab.id).read_text(encoding="utf-8") == "x"


def test_a_folder_that_does_not_exist_is_nothing_to_move(tmp_path):
    assert migrate_memos(tmp_path / "never-made") == []
