"""The API tabs a program lists in a file of its own (`api_tab_sources`): how the file is read
(`api_tab_source_file.py`, `api_tab_sources.py`), how its tabs join the table (`api_tab_table.py`), what their rows show
(`api_tab_rows.py`) and how the stream follows them (`api_tab_stream.py`)."""
from __future__ import annotations

import asyncio
import json
import logging
import os
import threading
from datetime import datetime

import pytest

from backend._common.state import sessions_overview
from backend.api_tabs import api_tab_record, api_tab_table, current_table, list_rows, overview_rows, sources, status_rows, stream
from backend.api_tabs.api_tab_source_file import parse_source_file
from backend.api_tabs.api_tab_sources import MAX_FILE_BYTES
from backend.tests.api_tabs.samples import TAB_ID, append, assistant_row, write_config

NOW = datetime.fromisoformat("2026-11-18T12:00:00+09:00")
WINDOW = 100000


def _row(name: str, folder, *, tokens: int | None = 0, spent: float = 0.01, title: str | None = None) -> dict:
    return {"name": name, "title": title or f"Group {name}", "record": str(folder / "conversations" / f"{name}.jsonl"),
            "context_tokens": tokens, "spend": {"month": "2026-11", "spent": spent, "limit": 50, "currency": "USD"},
            "generation": 1, "last_rollover_at": None}


def _write_tabs(env, *rows: dict, window: int | None = WINDOW, fields: list | None = None) -> None:
    """Replace the tab list file the way the program does: a temporary file renamed over it."""
    body = {"updated_at": "2026-11-18T12:00:00+09:00", "tabs": list(rows)}
    if window is not None:
        body["context_window"] = window
    if fields is not None:
        body["settings_fields"] = fields
    tmp = env.tabs.with_suffix(".tmp")
    tmp.write_text(json.dumps(body), encoding="utf-8")
    os.replace(tmp, env.tabs)


@pytest.fixture
def source_env(api_env, tmp_path):
    """`api_env` plus one source (`line-group`) whose tab list file and records live in the test's `bot/` folder."""
    folder = tmp_path / "bot"
    (folder / "conversations").mkdir(parents=True)
    api_env.folder = folder
    api_env.tabs = folder / "tabs.json"
    api_env.settings = tmp_path / "bot-config" / "settings.json"
    write_config(api_env,
                 api_accounts={"api": {"display_name": "API", "spend": str(api_env.spend)}},
                 api_tabs={"support-bot": {"title": "Support bot", "agent_id": "agent_a", "account": "api",
                                           "record": str(api_env.record)}},
                 api_tab_sources={"line-group": {"tabs": str(api_env.tabs), "agent_id": "agent_a", "account": "api",
                                                 "settings": str(api_env.settings)}})
    return api_env


def _poll() -> None:
    asyncio.run(stream.poll())


def _poll_wakes_the_overview() -> bool:
    """One look; → whether it woke the screens' overview."""
    woken = sessions_overview.subscribe()
    try:
        _poll()
        return woken.is_set()
    finally:
        sessions_overview.unsubscribe(woken)


def _ids() -> list[str]:
    return [row["id"] for row in list_rows(NOW)]


# --- the file -------------------------------------------------------------------------------------------------------


def test_a_row_with_a_bad_name_or_record_is_left_out_and_a_bad_figure_counts_as_none(tmp_path):
    reading = parse_source_file(json.dumps({"context_window": WINDOW, "tabs": [
        {"name": "G-Upper", "record": "/x.jsonl"},
        {"name": "g-rel", "record": "relative.jsonl"},
        {"name": "g-" + "a" * 70, "record": "/x.jsonl"},
        {"name": "g-ok", "title": 3, "record": "/x/g-ok.jsonl", "context_tokens": "12", "spend": {"spent": 1}},
        {"name": "g-ok", "record": "/x/again.jsonl"},
        "not a row",
    ]}))
    assert [row.name for row in reading.rows] == ["g-ok"]
    assert reading.rows[0].title == "g-ok"                                  # a title that is not a text is the name
    assert (reading.figures["g-ok"].context_tokens, reading.figures["g-ok"].spend) == (None, None)
    assert len(reading.problems) == 5


@pytest.mark.parametrize("window", [0, -5, 1.5, True, "100000", None])
def test_a_window_that_is_not_a_positive_whole_number_is_none(window):
    assert parse_source_file(json.dumps({"context_window": window, "tabs": []})).context_window is None


@pytest.mark.parametrize("text", ["", "[]", "{", json.dumps({"tabs": {}}), json.dumps({"context_window": 1})])
def test_a_text_that_is_not_a_tab_list_file_is_refused(text):
    with pytest.raises(ValueError):
        parse_source_file(text)


def test_a_settings_field_that_does_not_hold_together_is_left_out():
    good = {"key": "rollover_percent", "label": "入れ替え", "unit": "%", "min": 10, "max": 95, "step": 1, "default": 60}
    reading = parse_source_file(json.dumps({"tabs": [], "settings_fields": [
        good,
        {**good, "key": "Bad-Key"},
        {**good, "key": "no_label", "label": ""},
        {**good, "key": "outside", "default": 99},
        {**good, "key": "upside_down", "min": 95, "max": 10},
        {**good, "key": "zero_step", "step": 0},
        {**good, "key": "flag", "default": True},
        {**good, "label": "twice"},
    ]}))
    assert [field.key for field in reading.settings_fields] == ["rollover_percent"]
    assert reading.settings_fields[0].to_dict() == {**good}
    assert len(reading.problems) == 7


# --- the table and the rows -----------------------------------------------------------------------------------------


def test_a_backend_that_declares_only_a_source_lists_its_tabs_after_one_look(api_env, tmp_path):
    folder = tmp_path / "only"
    folder.mkdir()
    api_env.tabs = folder / "tabs.json"
    write_config(api_env, api_tab_sources={"only": {"tabs": str(api_env.tabs), "agent_id": "agent_a"}})
    _write_tabs(api_env, _row("g-a", folder))
    _poll()
    assert _ids() == ["api_g-a"]


def test_the_tabs_of_a_source_come_after_the_declared_tabs_with_their_window_and_amount(source_env):
    _write_tabs(source_env, _row("g-a", source_env.folder, tokens=42000), _row("g-b", source_env.folder, tokens=None))
    _poll()
    rows = {row["id"]: row for row in list_rows(NOW)}
    assert list(rows) == [TAB_ID, "api_g-a", "api_g-b"]
    assert (rows["api_g-a"]["kind"], rows["api_g-a"]["title"], rows["api_g-a"]["account_id"]) == ("api", "Group g-a", "api")
    assert (rows["api_g-a"]["context_tokens"], rows["api_g-a"]["context_window"]) == (42000, WINDOW)
    assert (rows["api_g-b"]["context_tokens"], rows["api_g-b"]["context_window"]) == (None, WINDOW)
    assert rows[TAB_ID]["context_window"] is None                            # a declared tab has no window
    overview = overview_rows(NOW)
    assert (overview["api_g-a"]["title"], overview["api_g-a"]["context_window"]) == ("Group g-a", WINDOW)


def test_a_row_added_or_removed_changes_the_tabs_and_tells_the_overview(source_env):
    _write_tabs(source_env, _row("g-a", source_env.folder))
    _poll()
    _write_tabs(source_env, _row("g-a", source_env.folder), _row("g-b", source_env.folder))
    assert _poll_wakes_the_overview()
    assert _ids() == [TAB_ID, "api_g-a", "api_g-b"]
    _write_tabs(source_env, _row("g-b", source_env.folder))
    _poll()
    assert _ids() == [TAB_ID, "api_g-b"]


def test_a_change_of_figures_only_tells_the_overview_but_does_not_build_the_table_again(source_env, caplog):
    _write_tabs(source_env, _row("g-a", source_env.folder, tokens=100))
    _poll()
    table = current_table()
    caplog.clear()                                  # the records of the first build are not this test's question
    with caplog.at_level(logging.INFO, logger="backend.api_tabs.api_tab_table"):
        _write_tabs(source_env, _row("g-a", source_env.folder, tokens=0, spent=0.02))   # a rollover: the amount is 0
        assert _poll_wakes_the_overview()
    assert current_table() is table
    assert not [record for record in caplog.records if "api tab: loaded" in record.getMessage()]
    row = status_rows(NOW)["api_g-a"]
    assert (row["context_tokens"], row["context_window"], row["spend"]["spent"], row["spend_scope"]) == (0, WINDOW, 0.02, "tab")


def test_only_the_tabs_that_came_are_written_to_the_log_when_the_table_is_built_again(source_env, caplog):
    _write_tabs(source_env, _row("g-a", source_env.folder))
    _poll()
    caplog.clear()                                  # the records of the first build are not this test's question
    with caplog.at_level(logging.INFO, logger="backend.api_tabs.api_tab_table"):
        _write_tabs(source_env, _row("g-a", source_env.folder), _row("g-b", source_env.folder))
        _poll()
    loaded = [record.getMessage() for record in caplog.records if "api tab: loaded" in record.getMessage()]
    assert len(loaded) == 1 and "api_g-b" in loaded[0]


def test_a_missing_file_lists_no_tab_and_a_broken_one_keeps_the_last_tabs(source_env, caplog):
    with caplog.at_level(logging.WARNING, logger="backend.api_tabs.api_tab_sources"):
        _poll()
    assert _ids() == [TAB_ID]
    assert any("tabs unreadable: file not found" in record.getMessage() for record in caplog.records)
    _write_tabs(source_env, _row("g-a", source_env.folder))
    _poll()
    source_env.tabs.write_text("{ broken", encoding="utf-8")
    _poll()
    assert _ids() == [TAB_ID, "api_g-a"]
    assert sources.unreadable_reason("line-group").startswith("not JSON")
    source_env.tabs.unlink()
    _poll()
    assert _ids() == [TAB_ID]


def test_a_file_larger_than_the_limit_keeps_the_last_tabs(source_env):
    _write_tabs(source_env, _row("g-a", source_env.folder))
    _poll()
    source_env.tabs.write_text(" " * (MAX_FILE_BYTES + 1), encoding="utf-8")
    _poll()
    assert _ids() == [TAB_ID, "api_g-a"] and "larger than" in sources.unreadable_reason("line-group")


def test_a_row_whose_record_is_outside_the_folder_of_the_file_is_left_out(source_env, tmp_path):
    outside = {**_row("g-out", source_env.folder), "record": str(tmp_path / "elsewhere.jsonl")}
    link = source_env.folder / "conversations" / "link.jsonl"
    link.symlink_to(tmp_path / "elsewhere.jsonl")
    linked = {**_row("g-link", source_env.folder), "record": str(link)}
    _write_tabs(source_env, outside, linked, _row("g-in", source_env.folder))
    _poll()
    assert _ids() == [TAB_ID, "api_g-in"]


def test_a_row_whose_id_is_already_a_tab_is_left_out_and_lends_it_no_figure(source_env):
    append(source_env.record, assistant_row("a1", "m1", "hi", usage={"input_tokens": 300}))
    _poll()
    _write_tabs(source_env, _row("support-bot", source_env.folder, tokens=99999), _row("g-a", source_env.folder))
    _poll()
    _poll()
    rows = {row["id"]: row for row in list_rows(NOW)}
    assert list(rows) == [TAB_ID, "api_g-a"]
    assert rows[TAB_ID]["title"] == "Support bot"
    assert rows[TAB_ID]["context_tokens"] == 300 and rows[TAB_ID]["context_window"] is None
    assert status_rows(NOW)[TAB_ID]["spend_scope"] == "wallet"


def test_the_record_of_a_source_tab_is_never_read_again_to_count_its_amount(source_env, monkeypatch):
    record = source_env.folder / "conversations" / "g-a.jsonl"
    append(record, assistant_row("a1", "m1", "hi", usage={"input_tokens": 300}))

    def counted(path):
        raise AssertionError(f"counted {path}")

    monkeypatch.setattr(api_tab_record, "last_context_tokens", counted)
    _write_tabs(source_env, _row("g-a", source_env.folder, tokens=None))
    _poll()
    _poll()
    append(record, assistant_row("a2", "m2", "again", usage={"input_tokens": 900}))
    record.write_text("")                                                 # shorter: a rewind
    _poll()
    assert status_rows(NOW)["api_g-a"]["context_tokens"] is None          # the source's none, never the record's 900


def test_a_file_renamed_over_with_the_same_size_and_time_is_read_again(source_env):
    _write_tabs(source_env, _row("g-a", source_env.folder, tokens=1000))
    _poll()
    stat = source_env.tabs.stat()
    tmp = source_env.tabs.with_suffix(".tmp")
    tmp.write_text(source_env.tabs.read_text().replace('"context_tokens": 1000', '"context_tokens": 2000'))
    os.utime(tmp, ns=(stat.st_atime_ns, stat.st_mtime_ns))
    os.replace(tmp, source_env.tabs)
    assert source_env.tabs.stat().st_size == stat.st_size
    _poll()
    assert status_rows(NOW)["api_g-a"]["context_tokens"] == 2000


def test_a_tab_whose_source_names_another_record_is_followed_from_that_files_end(source_env):
    first, second = (source_env.folder / "conversations" / name for name in ("first.jsonl", "second.jsonl"))
    append(first, assistant_row("a1", "m1", "one"))
    append(second, assistant_row("b1", "n1", "two"), assistant_row("b2", "n2", "three"))
    _write_tabs(source_env, {**_row("g-a", source_env.folder), "record": str(first)})
    _poll()
    _poll()
    _write_tabs(source_env, {**_row("g-a", source_env.folder), "record": str(second)})
    _poll()
    assert stream._offsets["api_g-a"] == second.stat().st_size


def test_a_source_taken_out_of_the_configuration_takes_its_tabs_away(source_env):
    _write_tabs(source_env, _row("g-a", source_env.folder))
    _poll()
    write_config(source_env, api_tabs={"support-bot": {"title": "Support bot", "agent_id": "agent_a",
                                                       "record": str(source_env.record)}})
    _poll()
    assert _ids() == [TAB_ID] and sources.rows("line-group") == ()


def test_threads_that_ask_at_once_after_a_change_get_one_table(source_env):
    _write_tabs(source_env, _row("g-a", source_env.folder))
    sources.look(current_table().source_paths())
    barrier, tables = threading.Barrier(8), []

    def ask() -> None:
        barrier.wait()
        tables.append(current_table())

    threads = [threading.Thread(target=ask) for _ in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert len({id(table) for table in tables}) == 1
    assert api_tab_table._loaded[2] is tables[0]
