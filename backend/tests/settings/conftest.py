"""A `config.json` the settings screen's tests change: a work account that moves its tabs to the personal one, a personal
account with a hold, two agents, written the way a person writes it (2-space indent, a trailing newline)."""
from __future__ import annotations

import json

import pytest

import backend._common.config as config

SETTINGS = {
    "notification_title": "通知",
    "claude_path": "/usr/bin/true",
    "accounts": {
        "work": {"display_name": "Work", "env": {"CLAUDE_CONFIG_DIR": "/nonexistent-work"},
                 "fallback": {"to": "personal", "at_pct": 95, "seven_day_at_pct": {"mon": 70}}},
        "personal": {"display_name": "個人", "env": {}, "hold": {"seven_day_at_pct": {"mon": 70, "sat": 100}}},
    },
    "agents": {
        "agent_a": {"cwd": "/a", "display_name": "Agent A", "launch_alias": "agent_a", "sleep": {"minutes": 60},
                    "rollover": {"working": {"context_pct": 60}, "idle": {"context_pct": 40, "minutes": 50}}},
        "agent_b": {"cwd": "/b", "launch_alias": "agent_b"},
    },
    "child_sessions_max": 5,
}


@pytest.fixture
def config_file(tmp_path, monkeypatch):
    """The file the client reads its settings from for this test; → its path."""
    path = tmp_path / "config.json"
    path.write_text(json.dumps(SETTINGS, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    path.chmod(0o640)
    monkeypatch.setattr(config, "CONFIG_PATH", path)
    config.get_config.cache_clear()
    yield path
    config.get_config.cache_clear()
