"""GET /settings and PUT /settings (`routes/settings.py`, `settings_view.py`)."""
from __future__ import annotations

import json
import time

import pytest
from fastapi import FastAPI
from starlette.testclient import TestClient

from backend._common.state import SleepMark, register_session
from backend.account_fallback.fallback_settings import WEEKDAYS
from backend.account_hold.hold_settings import HoldRule
from backend.routes import settings as settings_routes
from backend.settings import settings_view
from backend.tests.settings.conftest import SETTINGS


def usage_row(account, five=10, seven=10) -> dict:
    now = time.time()
    return {"timestamp": now - 5, "account_id": account, "five_hour_pct": five, "five_hour_resets_at": now + 3600,
            "seven_day_pct": seven, "seven_day_resets_at": now + 86400}


@pytest.fixture
def client(config_file, monkeypatch, isolated_state) -> TestClient:
    monkeypatch.setattr(settings_view, "read_all_rate_limits_tail",
                        lambda: [usage_row("work", five=30, seven=40), usage_row("personal", seven=55)])
    monkeypatch.setattr(isolated_state, "save_sessions_meta", lambda: None)
    app = FastAPI()
    app.include_router(settings_routes.router)
    return TestClient(app)


def _account(view, account_id):
    return next(account for account in view["accounts"] if account["id"] == account_id)


def test_get_shows_the_usage_and_the_lines_of_each_account(client):
    view = client.get("/settings").json()
    work, personal = _account(view, "work"), _account(view, "personal")
    assert (work["mode"], personal["mode"]) == ("fallback", "hold")
    assert work["usage"]["five_hour_pct"] == 30 and work["usage"]["seven_day_pct"] == 40
    assert work["usage"]["seven_day_resets_at"] > time.time()
    assert work["fallback"] == {"to": "personal", "to_display_name": "個人", "at_pct": 95, "ahead_pct": 0,
                                "seven_day_at_pct": {"mon": 70}, "seven_day_today_pct": work["fallback"]["seven_day_today_pct"]}
    assert personal["hold"]["seven_day_at_pct"] == {"mon": 70, "sat": 100} and personal["fallback"] is None
    assert personal["hold"]["five_hour_at_pct"] is None
    assert work["display_name"] == "Work" and personal["display_name"] == "個人"


def test_get_counts_the_tabs_a_line_stopped_and_says_whether_they_can_be_continued(client, monkeypatch):
    stopped = register_session("agent_a", "stopped", account_id="personal")
    stopped.held_at = 5.0
    stopped.sleep = SleepMark(claude_sid="c", record="/r", slept_at=1)
    register_session("agent_a", "free", account_id="personal")
    personal = _account(client.get("/settings").json(), "personal")
    assert personal["held_count"] == 1 and personal["can_continue"] is True
    every_day = {day: 50 for day in WEEKDAYS}                       # a line today whatever the day is
    monkeypatch.setattr(settings_view.hold_settings, "read_rules",
                        lambda: {"personal": HoldRule("personal", every_day)})
    monkeypatch.setattr(settings_view, "read_all_rate_limits_tail", lambda: [usage_row("personal", seven=60)])
    personal = _account(client.get("/settings").json(), "personal")
    assert personal["held_count"] == 1 and personal["can_continue"] is False and personal["hold"]["today_pct"] == 50
    monkeypatch.setattr(settings_view, "read_all_rate_limits_tail", lambda: [usage_row("personal", seven=40)])
    assert _account(client.get("/settings").json(), "personal")["can_continue"] is True


def test_get_counts_the_tabs_on_each_account_by_what_they_are_doing(client):
    register_session("agent_a", "awake", account_id="personal")
    pinned = register_session("agent_a", "pinned", account_id="personal", account_pinned=True)
    stopped = register_session("agent_a", "stopped", account_id="personal")
    stopped.held_at = 5.0
    stopped.sleep = SleepMark(claude_sid="c", record="/r", slept_at=1)
    register_session("agent_a", "elsewhere", account_id="work")
    view = client.get("/settings").json()
    assert _account(view, "personal")["tabs"] == {"total": 3, "running": 2, "pinned": 1, "held": 1}
    assert _account(view, "work")["tabs"] == {"total": 1, "running": 1, "pinned": 0, "held": 0}
    assert pinned.account_pinned


def test_get_lists_the_tabs_pinned_to_an_account(client):
    pinned = register_session("agent_a", "pinned", account_id="work", account_pinned=True)
    register_session("agent_a", "not pinned", account_id="work")
    assert _account(client.get("/settings").json(), "work")["pinned_tabs"] == [{"id": pinned.id, "title": "pinned"}]


def test_get_shows_the_sleep_and_the_rollover_of_each_agent_the_title_and_the_limit(client):
    view = client.get("/settings").json()
    agent_a, agent_b = view["agents"]
    assert agent_a == {"id": "agent_a", "display_name": "Agent A", "sleep_minutes": 60, "sleep_pressure_minutes": None,
                       "rollover": {"working_context_pct": 60, "idle_context_pct": 40, "idle_minutes": 50}}
    assert agent_b["sleep_minutes"] is None and agent_b["rollover"]["idle_minutes"] is None
    assert (view["child_sessions_max"], view["notification_title"]) == (5, "通知")


def test_get_shows_no_limit_on_the_child_tabs_as_null_once_the_field_is_removed(client):
    answer = client.put("/settings", json={"child_sessions_max": None})
    assert answer.status_code == 200 and answer.json()["child_sessions_max"] is None
    assert client.get("/settings").json()["child_sessions_max"] is None


def test_get_shows_the_running_version_the_start_time_and_the_last_stall(client, tmp_path, monkeypatch):
    machine = client.get("/settings").json()["machine"]
    assert machine["version"] == settings_view.RUNNING_VERSION and machine["backend_started_at"] > 0
    log = tmp_path / "loop-stall.log"
    log.write_text("File \"x\", line 1\n--- the stacks above: loop stood still 20s, back at 2026-11-09T10:00:00 ---\n"
                   "File \"y\"\n--- the stacks above: loop stood still 31s, back at 2026-11-09T11:30:00 ---\n")
    assert settings_view.last_loop_stall(tmp_path) == {"stood_still_sec": 31, "back_at": "2026-11-09T11:30:00"}
    assert settings_view.last_loop_stall(tmp_path / "nowhere") is None
    log.write_text("File \"x\", line 1\n")
    assert settings_view.last_loop_stall(tmp_path) is None


def test_put_changes_the_allowed_fields_writes_the_file_and_answers_with_the_new_view(client, config_file):
    answer = client.put("/settings", json={"accounts": {"personal": {"hold": {"seven_day_at_pct": {"mon": 60}}}},
                                           "agents": {"agent_a": {"sleep": {"minutes": 25}}}, "child_sessions_max": 3})
    assert answer.status_code == 200
    view = answer.json()
    assert _account(view, "personal")["hold"]["seven_day_at_pct"]["mon"] == 60
    assert view["agents"][0]["sleep_minutes"] == 25 and view["child_sessions_max"] == 3
    written = json.loads(config_file.read_text(encoding="utf-8"))
    assert written["accounts"]["personal"]["hold"]["seven_day_at_pct"] == {"mon": 60, "sat": 100}
    assert written["agents"]["agent_a"]["sleep"]["minutes"] == 25 and written["claude_path"] == SETTINGS["claude_path"]


def test_put_answers_400_with_every_reason_for_a_field_outside_the_list_and_writes_nothing(client, config_file):
    before = config_file.read_bytes()
    answer = client.put("/settings", json={"claude_path": "/bin/sh", "agents": {"agent_a": {"sleep": {"minutes": 0}}}})
    assert answer.status_code == 400
    detail = answer.json()["detail"]
    assert detail["code"] == "settings_rejected" and len(detail["params"]["reasons"]) == 2
    assert config_file.read_bytes() == before


def test_put_answers_400_for_a_body_that_names_nothing(client):
    assert client.put("/settings", json={}).status_code == 400


def test_put_answers_500_when_the_file_cannot_be_read(client, config_file):
    config_file.write_text("{ nope", encoding="utf-8")
    answer = client.put("/settings", json={"child_sessions_max": 2})
    assert answer.status_code == 500 and answer.json()["detail"]["code"] == "settings_not_written"


def test_get_shows_the_width_ahead_of_the_line_and_the_line_of_the_5_hours_and_the_limits_of_both(client, config_file):
    answer = client.put("/settings", json={"accounts": {"work": {"fallback": {"ahead_pct": 5}},
                                                       "personal": {"hold": {"five_hour_at_pct": 95}}}})
    assert answer.status_code == 200
    view = client.get("/settings").json()
    assert _account(view, "work")["fallback"]["ahead_pct"] == 5
    assert _account(view, "personal")["hold"]["five_hour_at_pct"] == 95
    assert (view["limits"]["ahead_pct_min"], view["limits"]["ahead_pct_max"]) == (0, 50)
    written = json.loads(config_file.read_text(encoding="utf-8"))
    assert written["accounts"]["work"]["fallback"]["ahead_pct"] == 5
    assert written["accounts"]["personal"]["hold"]["five_hour_at_pct"] == 95


def test_get_cannot_continue_while_the_5_hours_are_at_their_line(client, config_file, monkeypatch):
    client.put("/settings", json={"accounts": {"personal": {"hold": {"five_hour_at_pct": 95}}}})
    stopped = register_session("agent_a", "stopped", account_id="personal")
    stopped.held_at = 5.0
    stopped.sleep = SleepMark(claude_sid="c", record="/r", slept_at=1)
    monkeypatch.setattr(settings_view, "read_all_rate_limits_tail",
                        lambda: [usage_row("personal", five=96, seven=10)])
    assert _account(client.get("/settings").json(), "personal")["can_continue"] is False
    monkeypatch.setattr(settings_view, "read_all_rate_limits_tail",
                        lambda: [usage_row("personal", five=90, seven=10)])
    assert _account(client.get("/settings").json(), "personal")["can_continue"] is True
