"""The settings a tab's tier replaces (`agents.<agent>.tiers.<tier>`), as the rollover and the sleep read them."""
from __future__ import annotations

import pytest

import backend._common.config as config_mod
from backend._common.state import SessionDef
from backend.rollover import rollover
from backend.sleep import sleep_settings
from backend.terminal import session_resolver

AGENT_DEFAULT = {"working": {"context_pct": 60}, "idle": {"context_pct": 40, "minutes": 50}}
NORMAL_ONLY = {"working": {"context_pct": 60}}
NARROW = {"working": {"context_pct": 45}, "idle": {"context_pct": 30, "minutes": 50}}
AGENTS = {
    "agent_a": {"cwd": "/a", "rollover": AGENT_DEFAULT, "sleep": {"minutes": 60, "pressure_minutes": 10},
                "tiers": {"normal": {"rollover": NORMAL_ONLY, "sleep": None}}},
    "agent_b": {"cwd": "/b", "rollover": AGENT_DEFAULT, "sleep": {"minutes": 60},
                "tiers": {"normal": {"rollover": NARROW, "sleep": {"minutes": 60}}}},
    "agent_sub": {"cwd": "/b", "rollover": AGENT_DEFAULT, "sleep": {"minutes": 60}},
    "agent_broken": {"cwd": "/c", "rollover": AGENT_DEFAULT, "tiers": ["normal"]},
    "agent_broken_tier": {"cwd": "/c", "rollover": AGENT_DEFAULT, "tiers": {"normal": "off"}},
}


@pytest.fixture
def tab(monkeypatch, isolated_state):
    monkeypatch.setattr(config_mod, "AGENTS", AGENTS)

    def make(agent: str, tier: str | None, *, tier_tab: str | None = None, child: bool = False) -> str:
        sid = f"ses_{agent}_{tier}_{tier_tab}_{child}".replace("/", "_")
        isolated_state.sessions_meta[sid] = SessionDef(id=sid, agent_id=agent, title=sid, created_at=0, tier=tier,
                                                       tier_tab=tier_tab, child=child)
        return sid

    return make


def _read(sid: str) -> tuple:
    return (rollover.settings_for(sid), sleep_settings.sleep_minutes(sid), sleep_settings.pressure_minutes(sid),
            sleep_settings.rollover_idle_pct(sid))


@pytest.mark.parametrize(("agent", "tier", "expected"), [
    ("agent_a", "normal", (NORMAL_ONLY, None, None, None)),
    ("agent_a", "projects/music", (AGENT_DEFAULT, 60, 10, 40)),
    ("agent_a", "projects/game/subprojects/heads", (AGENT_DEFAULT, 60, 10, 40)),
    ("agent_b", "normal", (NARROW, 60, None, 30)),
    ("agent_b", "projects/tools", (AGENT_DEFAULT, 60, None, 40)),
    ("agent_sub", "normal", (AGENT_DEFAULT, 60, None, 40)),
    ("agent_a", None, (NORMAL_ONLY, None, None, None)),
    ("agent_a", "Normal", (AGENT_DEFAULT, 60, 10, 40)),
    ("agent_broken", "normal", (AGENT_DEFAULT, None, None, 40)),
    ("agent_broken_tier", "normal", (AGENT_DEFAULT, None, None, 40)),
], ids=lambda value: str(value))
def test_a_tier_replaces_the_agent_s_sections(tab, agent, tier, expected):
    assert _read(tab(agent, tier)) == expected


def test_a_child_of_an_agent_without_a_child_agent_reads_its_parent_s_tier(tab):
    assert rollover.settings_for(tab("agent_a", "normal", child=True)) == NORMAL_ONLY


def test_a_placed_tier_tab_not_started_yet_reads_its_tier(tab):
    assert rollover.settings_for(tab("agent_a", None, tier_tab="projects/music")) == AGENT_DEFAULT


def test_a_section_the_tier_leaves_out_is_the_agent_s(tab, monkeypatch):
    agents = {"agent_a": {**AGENTS["agent_a"], "tiers": {"normal": {"sleep": None}}}}
    monkeypatch.setattr(config_mod, "AGENTS", agents)
    sid = tab("agent_a", "normal")
    assert rollover.settings_for(sid) == AGENT_DEFAULT and sleep_settings.sleep_minutes(sid) is None


def test_the_other_keys_of_an_agent_are_not_replaced(tab, monkeypatch):
    agents = {"agent_a": {**AGENTS["agent_a"], "tiers": {"normal": {"cwd": "/elsewhere"}}}}
    monkeypatch.setattr(config_mod, "AGENTS", agents)
    sid = tab("agent_a", "normal")
    assert session_resolver.agent_setting(sid, "cwd") == "/a"
    assert session_resolver.resolve_agent_cfg(sid)["cwd"] == "/a"


def test_a_tab_the_settings_do_not_know_reads_nothing(isolated_state):
    assert session_resolver.agent_setting("ses_unknown", "rollover") is None


def test_what_is_miswritten_in_the_tiers_is_named(tmp_path):
    (tmp_path / "projects" / "music").mkdir(parents=True)
    agents = {"agent_a": {"cwd": str(tmp_path), "tiers": {"normal": {"rolover": {}}, "projects/music": {"sleep": None},
                                                          "projects/gone": {}, "normal2": "off"}},
              "agent_b": {"cwd": str(tmp_path), "tiers": ["normal"]}, "agent_c": {"cwd": str(tmp_path)}}
    problems = config_mod.tier_setting_problems(agents)
    assert problems == [
        "config.agents.agent_a.tiers.normal.rolover: a tier replaces only rollover, sleep",
        f"config.agents.agent_a.tiers.projects/gone: no such tier folder: {tmp_path / 'projects' / 'gone'}",
        "config.agents.agent_a.tiers.normal2 must be an object",
        "config.agents.agent_b.tiers must be an object of tiers",
    ]


def test_a_tier_s_pressure_minutes_are_checked_as_the_agent_s():
    from backend.settings.settings_fields import _sleep_problems  # noqa: PLC0415
    agents = {"agent_a": {"sleep": {"minutes": 60}, "tiers": {"normal": {"sleep": {"minutes": 30, "pressure_minutes": 40}}}}}
    assert _sleep_problems(agents) == ["agents.agent_a.tiers.normal.sleep.pressure_minutes: must be 30 or less "
                                       "(= `minutes`), got 40"]
