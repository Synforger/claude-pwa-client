"""The settings of a program that lists API tabs, on the settings screen (`api_tabs/api_source_settings.py`,
`PUT /settings/api-sources/{source}`): the fields come from the program's tab list file, the path from the client's own
configuration, and a write changes only the values sent, inside the ranges declared."""
from __future__ import annotations

import json
import os
import stat

import pytest
from fastapi import FastAPI
from starlette.testclient import TestClient

import backend._common.config as config
from backend.api_tabs import api_tab_table, sources, stream, write_values
from backend.api_tabs.api_source_settings import SettingsRejected
from backend.routes import settings as settings_routes
from backend.settings import settings_view
from backend.tests.settings.conftest import SETTINGS

FIELDS = [
    {"key": "monthly_budget_usd", "label": "月の予算", "unit": "USD", "min": 1, "max": 1000, "step": 1, "default": 100},
    {"key": "rollover_percent", "label": "入れ替え", "unit": "%", "min": 10, "max": 95, "step": 1, "default": 60},
    {"key": "idle_hours", "label": "静か", "unit": "時間", "min": 0.5, "max": 48, "step": 0.5, "default": 6},
]


@pytest.fixture
def with_source(config_file, monkeypatch, isolated_state, tmp_path):
    """The screen's settings plus one source (`line-group`) whose tab list file declares `FIELDS`; → a namespace with
    the paths and a client of the settings routes."""
    from types import SimpleNamespace  # noqa: PLC0415

    folder = tmp_path / "bot"
    folder.mkdir()
    settings_dir = tmp_path / "bot-config"
    settings_dir.mkdir()
    env = SimpleNamespace(tabs=folder / "tabs.json", settings=settings_dir / "settings.json", config_file=config_file)
    env.tabs.write_text(json.dumps({"context_window": 100000, "settings_fields": FIELDS, "tabs": []}))
    _declare(env, {"tabs": str(env.tabs), "agent_id": "agent_a", "settings": str(env.settings)})
    monkeypatch.setattr(settings_view, "read_all_rate_limits_tail", lambda: [])
    app = FastAPI()
    app.include_router(settings_routes.router)
    env.client = TestClient(app)
    yield env
    stream.__init__()
    sources.__init__()
    api_tab_table._loaded = (None, -1, api_tab_table.ApiTabTable([], [], []))


def _declare(env, source: dict | None) -> None:
    extra = {} if source is None else {"api_tab_sources": {"line-group": source}}
    env.config_file.write_text(json.dumps({**SETTINGS, **extra}, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    config.get_config.cache_clear()
    sources.__init__()
    sources.look(api_tab_table.current_table().source_paths())


def _view(env) -> dict:
    return env.client.get("/settings").json()["api_sources"][0]


def _put(env, values, source: str = "line-group"):
    return env.client.put(f"/settings/api-sources/{source}", json={"values": values})


def test_the_screen_shows_the_programs_fields_with_the_files_values_and_the_defaults(with_source):
    with_source.settings.write_text(json.dumps({"rollover_percent": 70, "idle_hours": "six"}))
    view = _view(with_source)
    assert [field["key"] for field in view["fields"]] == ["monthly_budget_usd", "rollover_percent", "idle_hours"]
    assert view["values"] == {"monthly_budget_usd": 100, "rollover_percent": 70, "idle_hours": 6}
    assert (view["problem"], view["tabs_unreadable"]) == (None, None)


def test_a_source_that_offers_nothing_says_why_with_a_code(with_source):
    _declare(with_source, {"tabs": str(with_source.tabs), "agent_id": "agent_a"})
    assert (_view(with_source)["problem"], _view(with_source)["fields"]) == ("no_settings", [])
    _declare(with_source, {"tabs": str(with_source.tabs), "agent_id": "agent_a", "settings": str(with_source.settings)})
    with_source.tabs.write_text(json.dumps({"tabs": []}))
    sources.look(api_tab_table.current_table().source_paths())
    assert _view(with_source)["problem"] == "no_fields"
    with_source.tabs.write_text("{ broken")
    sources.look(api_tab_table.current_table().source_paths())
    assert _view(with_source)["tabs_unreadable"].startswith("not JSON")


def test_a_settings_file_the_screen_cannot_read_is_named_and_shown_with_the_defaults(with_source):
    with_source.settings.write_text("[1, 2]")
    view = _view(with_source)
    assert view["problem"] == "settings_unreadable" and "not a JSON object" in view["reason"]
    assert view["values"]["monthly_budget_usd"] == 100


def test_a_write_changes_only_the_values_sent_and_keeps_the_other_keys_their_order_and_the_mode(with_source):
    with_source.settings.write_text(json.dumps({"note": "kept", "rollover_percent": 60, "monthly_budget_usd": 100}))
    with_source.settings.chmod(0o600)
    reply = _put(with_source, {"monthly_budget_usd": 50.0, "idle_hours": 1.5})
    assert reply.status_code == 200
    written = with_source.settings.read_text()
    assert list(json.loads(written)) == ["note", "rollover_percent", "monthly_budget_usd", "idle_hours"]
    assert json.loads(written) == {"note": "kept", "rollover_percent": 60, "monthly_budget_usd": 50, "idle_hours": 1.5}
    assert '"monthly_budget_usd": 50,' in written                          # a whole-number field is written whole
    assert stat.S_IMODE(with_source.settings.stat().st_mode) == 0o600
    assert reply.json()["api_sources"][0]["values"]["monthly_budget_usd"] == 50


def test_the_first_write_makes_a_file_others_can_read(with_source):
    assert _put(with_source, {"rollover_percent": 50}).status_code == 200
    assert json.loads(with_source.settings.read_text()) == {"rollover_percent": 50}
    assert stat.S_IMODE(with_source.settings.stat().st_mode) == 0o644


def test_a_write_through_a_link_replaces_the_file_it_points_to(with_source, tmp_path):
    target = tmp_path / "real-settings.json"
    target.write_text(json.dumps({"rollover_percent": 60}))
    with_source.settings.symlink_to(target)
    assert _put(with_source, {"rollover_percent": 80}).status_code == 200
    assert with_source.settings.is_symlink() and json.loads(target.read_text()) == {"rollover_percent": 80}


@pytest.mark.parametrize("values", [
    {"rollover_percent": 99},                    # above the range
    {"rollover_percent": 5},                     # below it
    {"color": 1},                                # a field the program does not declare
    {"rollover_percent": True},                  # not a number
    {"rollover_percent": "60"},
    {"idle_hours": 1.25},                        # off the grid of 0.5
    {"rollover_percent": 60.5},                  # off the grid of 1
    {},
])
def test_a_value_that_may_not_be_written_is_refused_and_the_file_is_untouched(with_source, values):
    with_source.settings.write_text('{"rollover_percent": 60}')
    reply = _put(with_source, values)
    assert reply.status_code == 400 and reply.json()["detail"]["code"] == "settings_rejected"
    assert reply.json()["detail"]["params"]["reasons"]
    assert with_source.settings.read_text() == '{"rollover_percent": 60}'


def test_a_value_that_is_not_finite_is_refused():
    from backend.api_tabs.api_tab_source_file import parse_source_file  # noqa: PLC0415
    fields = parse_source_file(json.dumps({"tabs": [], "settings_fields": FIELDS})).settings_fields
    with pytest.raises(SettingsRejected):
        write_values(None, fields, {"rollover_percent": float("nan")})
    with pytest.raises(SettingsRejected):
        write_values(None, fields, {"rollover_percent": float("inf")})


def test_a_settings_file_that_is_not_an_object_is_not_written_over(with_source):
    with_source.settings.write_text("[1, 2]")
    reply = _put(with_source, {"rollover_percent": 50})
    assert reply.status_code == 500 and reply.json()["detail"]["code"] == "settings_not_written"
    assert with_source.settings.read_text() == "[1, 2]"


def test_a_settings_file_whose_folder_is_missing_is_a_write_that_fails(with_source):
    os.rmdir(with_source.settings.parent)
    assert _put(with_source, {"rollover_percent": 50}).status_code == 500


def test_an_unknown_source_is_404_and_one_without_a_settings_file_is_refused(with_source):
    reply = _put(with_source, {"rollover_percent": 50}, source="nobody")
    assert reply.status_code == 404 and reply.json()["detail"]["code"] == "api_source_unknown"
    _declare(with_source, {"tabs": str(with_source.tabs), "agent_id": "agent_a"})
    reply = _put(with_source, {"rollover_percent": 50})
    assert reply.status_code == 400 and reply.json()["detail"]["code"] == "settings_rejected"
