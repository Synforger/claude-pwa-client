"""Writing the settings screen's changes into `config.json` and having the client read it again
(`settings_store.py`, `config.reload_config`). The file is a real one in the test's own folder."""
from __future__ import annotations

import json
import logging
import os
import stat

import pytest

import backend._common.config as config
from backend._common.state import register_session
from backend.account_fallback import fallback_settings
from backend.account_hold import hold_settings
from backend.settings import settings_store
from backend.settings.settings_fields import Rejected
from backend.settings.settings_store import update_settings
from backend.sleep.sleep_settings import rollover_idle_pct, sleep_minutes
from backend.terminal import session_resolver
from backend.tests.settings.conftest import SETTINGS


def test_the_changed_field_is_written_and_every_other_field_keeps_its_value_its_place_and_the_files_form(config_file):
    before = config_file.read_text(encoding="utf-8")
    assert update_settings({"child_sessions_max": 2}) == ["child_sessions_max"]
    after = json.loads(config_file.read_text(encoding="utf-8"))
    assert after == {**SETTINGS, "child_sessions_max": 2} and list(after) == list(SETTINGS)
    assert config_file.read_text(encoding="utf-8") == before.replace('"child_sessions_max": 5', '"child_sessions_max": 2')


def test_a_file_that_is_not_indented_by_two_keeps_its_own_indent_and_the_japanese_text_stays_readable(config_file):
    config_file.write_text(json.dumps(SETTINGS, indent=4, ensure_ascii=False), encoding="utf-8")
    update_settings({"notification_title": "お知らせ"})
    text = config_file.read_text(encoding="utf-8")
    assert '    "notification_title": "お知らせ"' in text and not text.endswith("\n") and "\\u" not in text


def test_the_mode_of_the_file_is_kept_and_no_temporary_file_is_left(config_file):
    update_settings({"child_sessions_max": 3})
    assert stat.S_IMODE(config_file.stat().st_mode) == 0o640
    assert os.listdir(config_file.parent) == ["config.json"]


def test_a_refused_update_leaves_the_file_as_it_was(config_file):
    before = config_file.read_bytes()
    with pytest.raises(Rejected):
        update_settings({"child_sessions_max": 3, "claude_path": "/bin/sh"})
    assert config_file.read_bytes() == before and os.listdir(config_file.parent) == ["config.json"]


def test_a_file_that_cannot_be_read_is_an_error_and_not_an_empty_configuration(config_file):
    config_file.write_text("{ not json", encoding="utf-8")
    with pytest.raises(ValueError):
        update_settings({"child_sessions_max": 3})
    assert config_file.read_text(encoding="utf-8") == "{ not json"


def test_a_failure_while_writing_keeps_the_old_file_and_leaves_no_temporary_file(config_file, monkeypatch):
    before = config_file.read_bytes()

    def broken(*_args):
        raise OSError("disk full")
    monkeypatch.setattr(settings_store.os, "replace", broken)
    with pytest.raises(OSError):
        update_settings({"child_sessions_max": 3})
    assert config_file.read_bytes() == before and os.listdir(config_file.parent) == ["config.json"]


def test_a_symbolic_link_to_the_file_stays_a_link_and_the_target_is_written(config_file, tmp_path, monkeypatch):
    link = tmp_path / "link.json"
    link.symlink_to(config_file)
    monkeypatch.setattr(config, "CONFIG_PATH", link)
    update_settings({"child_sessions_max": 1})
    assert link.is_symlink() and json.loads(config_file.read_text(encoding="utf-8"))["child_sessions_max"] == 1


def test_the_log_names_the_fields_that_changed(config_file, caplog):
    caplog.set_level(logging.INFO, logger=settings_store.logger.name)
    update_settings({"child_sessions_max": 2, "notification_title": "x"})
    assert "settings: changed child_sessions_max, notification_title" in caplog.text


# --- the next look works with the new values ---------------------------------------------------------------------

def test_the_lines_of_the_fallback_and_of_the_hold_are_read_again(config_file):
    assert hold_settings.read_rules()["personal"].seven_day_at_pct == {"mon": 70, "sat": 100}
    update_settings({"accounts": {"personal": {"hold": {"seven_day_at_pct": {"mon": 60, "sat": None}}},
                                  "work": {"fallback": {"at_pct": 85}}}})
    assert hold_settings.read_rules()["personal"].seven_day_at_pct == {"mon": 60}
    assert fallback_settings.read_rules()["work"].at_pct == 85


def test_the_sleep_and_the_rollover_of_an_agent_are_read_again_by_the_code_that_binds_the_agents_at_import(
        config_file, monkeypatch):
    """`terminal/session_resolver.py` holds `AGENTS` from the moment it was imported (= bound here to the dict of this
    test's configuration, as it is bound to the running client's); it must see the new values."""
    monkeypatch.setattr(session_resolver, "AGENTS", config.AGENTS)
    tab = register_session("agent_a", "T")
    assert sleep_minutes(tab.id) == 60 and rollover_idle_pct(tab.id) == 40
    update_settings({"agents": {"agent_a": {"sleep": {"minutes": 20}, "rollover": {"idle": {"context_pct": 30}}}}})
    assert sleep_minutes(tab.id) == 20 and rollover_idle_pct(tab.id) == 30


def test_the_child_limit_the_removal_of_it_and_the_notification_title_are_read_again(config_file):
    assert config.CHILD_SESSIONS_MAX == 5 and config.NOTIFICATION_TITLE_DEFAULT == "通知"
    update_settings({"child_sessions_max": 1, "notification_title": "New"})
    assert config.CHILD_SESSIONS_MAX == 1 and config.NOTIFICATION_TITLE_DEFAULT == "New"
    update_settings({"child_sessions_max": None, "notification_title": None})
    assert config.CHILD_SESSIONS_MAX is None
    assert config.NOTIFICATION_TITLE_DEFAULT == "Notification"


def test_reading_again_keeps_the_dict_of_the_agents_that_modules_hold_and_follows_a_file_edited_by_hand(config_file):
    held = config.AGENTS
    edited = json.loads(config_file.read_text(encoding="utf-8"))
    edited["agents"]["agent_c"] = {"cwd": "/c"}
    del edited["agents"]["agent_b"]
    config_file.write_text(json.dumps(edited), encoding="utf-8")
    config.reload_config()
    assert config.AGENTS is held and set(held) == {"agent_a", "agent_c"}


def test_a_file_that_cannot_be_read_does_not_replace_what_the_client_holds(config_file):
    assert config.get_config()["child_sessions_max"] == 5
    config_file.write_text("{ not json", encoding="utf-8")
    with pytest.raises(ValueError):
        config.reload_config()
    assert config.get_config()["child_sessions_max"] == 5
