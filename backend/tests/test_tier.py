"""What a tier is (`terminal/tier.py`) and how the tier a tab's agent started in is read and remembered
(`terminal/tab_tier.py`)."""
from __future__ import annotations

import os
import subprocess
import sys
import pytest

from backend.terminal import tab_tier
from backend.terminal.tier import parse_tier, tier_path


@pytest.mark.parametrize("value, tier", [
    ("normal", "normal"),
    ("projects/alpha", "projects/alpha"),
    ("projects/alpha/subprojects/beta", "projects/alpha/subprojects/beta"),
    ("projects//alpha/", "projects/alpha"),
    ("projects/アルファ", "projects/アルファ"),
    (None, None),
    ("", None),
    ("/etc", None),
    ("..", None),
    ("projects/../..", None),
    ("projects/./alpha", "projects/alpha"),
    (".", None),
])
def test_a_value_names_a_tier_only_when_it_stays_inside_the_folder(value, tier):
    assert parse_tier(value) == tier


def test_a_tier_points_at_a_folder_below_the_agent_and_normal_at_the_agent_itself(tmp_path):
    assert tier_path(tmp_path, "normal") == tmp_path
    assert tier_path(tmp_path, None) == tmp_path
    assert tier_path(tmp_path, "projects/alpha") == tmp_path / "projects" / "alpha"


def spawn_with(environment: dict[str, str]) -> subprocess.Popen:
    """A process that waits, started with `environment` added to a minimal one."""
    return subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"],
                            env={"PATH": os.environ["PATH"], **environment})


@pytest.fixture
def waiting():
    started: list[subprocess.Popen] = []

    def start(**environment: str) -> int:
        process = spawn_with(environment)
        started.append(process)
        return process.pid

    yield start
    for process in started:
        process.kill()
        process.wait()


@pytest.fixture(autouse=True)
def clean_registry(monkeypatch):
    monkeypatch.setattr(tab_tier, "_tiers", {})


def test_the_tier_is_read_from_the_environment_of_the_claude_process(waiting):
    assert tab_tier.read_tier(waiting(AGENT_TIER="projects/alpha")) == "projects/alpha"
    assert tab_tier.read_tier(waiting()) is None
    assert tab_tier.read_tier(waiting(AGENT_TIER="../outside")) is None


def test_a_process_that_is_gone_has_no_tier():
    process = spawn_with({"AGENT_TIER": "normal"})
    pid = process.pid
    process.kill()
    process.wait()
    assert tab_tier.read_tier(pid) is None


def test_a_recorded_tier_is_what_the_tab_lists_and_a_new_value_is_reported_once(waiting):
    pid = waiting(AGENT_TIER="projects/alpha")
    assert tab_tier.tab_tier("ses_a") is None
    assert tab_tier.record_tier("ses_a", pid) is True
    assert tab_tier.tab_tier("ses_a") == "projects/alpha"
    assert tab_tier.record_tier("ses_a", pid) is False


def test_a_tab_whose_claude_was_given_no_tier_is_recorded_with_none_and_still_reported_once(waiting):
    pid = waiting()
    assert tab_tier.record_tier("ses_a", pid) is True
    assert tab_tier.tab_tier("ses_a") is None
    assert tab_tier.record_tier("ses_a", pid) is False


def test_a_restarted_claude_replaces_the_tier(waiting):
    tab_tier.record_tier("ses_a", waiting(AGENT_TIER="projects/alpha"))
    assert tab_tier.record_tier("ses_a", waiting(AGENT_TIER="normal")) is True
    assert tab_tier.tab_tier("ses_a") == "normal"


def test_a_forgotten_tab_has_no_tier(waiting):
    tab_tier.record_tier("ses_a", waiting(AGENT_TIER="normal"))
    tab_tier.forget_tier("ses_a")
    assert tab_tier.tab_tier("ses_a") is None
    tab_tier.forget_tier("ses_a")

