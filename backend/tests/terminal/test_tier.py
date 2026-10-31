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
    """A process that waits, started with `environment` added to a minimal one. Returns once the process
    runs Python: until then Linux shows the environment of the parent it was forked from."""
    process = subprocess.Popen([sys.executable, "-c", "import time; print(flush=True); time.sleep(60)"],
                               env={"PATH": os.environ["PATH"], **environment}, stdout=subprocess.PIPE)
    process.stdout.readline()
    return process


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
        process.stdout.close()


@pytest.fixture(autouse=True)
def a_tab_named_ses_a(isolated_state):
    isolated_state.register_session("agent_a", title="A", sid="ses_a")


def test_the_tier_is_read_from_the_environment_of_the_claude_process(waiting):
    assert tab_tier.read_tier(waiting(AGENT_TIER="projects/alpha")) == "projects/alpha"
    assert tab_tier.read_tier(waiting()) is None
    assert tab_tier.read_tier(waiting(AGENT_TIER="../outside")) is None


def test_a_process_that_is_gone_has_no_tier():
    process = spawn_with({"AGENT_TIER": "normal"})
    pid = process.pid
    process.kill()
    process.wait()
    process.stdout.close()
    assert tab_tier.read_tier(pid) is None


def test_a_recorded_tier_is_what_the_tab_lists_and_a_new_value_is_reported_once(waiting):
    pid = waiting(AGENT_TIER="projects/alpha")
    assert tab_tier.tab_tier("ses_a") is None
    assert tab_tier.record_tier("ses_a", pid) is True
    assert tab_tier.tab_tier("ses_a") == "projects/alpha"
    assert tab_tier.record_tier("ses_a", pid) is False


def test_a_tab_whose_claude_was_given_no_tier_has_none_and_nothing_is_reported(waiting):
    assert tab_tier.record_tier("ses_a", waiting()) is False
    assert tab_tier.tab_tier("ses_a") is None


def test_a_restarted_claude_replaces_the_tier(waiting):
    tab_tier.record_tier("ses_a", waiting(AGENT_TIER="projects/alpha"))
    assert tab_tier.record_tier("ses_a", waiting(AGENT_TIER="normal")) is True
    assert tab_tier.tab_tier("ses_a") == "normal"


def test_a_claude_that_names_no_tier_leaves_what_is_known(waiting):
    tab_tier.record_tier("ses_a", waiting(AGENT_TIER="projects/alpha"))
    assert tab_tier.record_tier("ses_a", waiting()) is False
    assert tab_tier.tab_tier("ses_a") == "projects/alpha"


def test_a_recorded_tier_is_written_to_disk_and_read_back_when_the_backend_starts_again(waiting, isolated_state):
    """A restart of the backend or the machine ends every claude; the tab keeps its tier without one."""
    tab_tier.record_tier("ses_a", waiting(AGENT_TIER="projects/alpha"))
    isolated_state.sessions_meta.clear()
    assert tab_tier.tab_tier("ses_a") is None

    isolated_state.sessions_meta.update(isolated_state._load_sessions_meta())
    assert tab_tier.tab_tier("ses_a") == "projects/alpha"


def test_a_tab_the_backend_does_not_list_has_no_tier_and_records_none(waiting):
    assert tab_tier.tab_tier("ses_unknown") is None
    assert tab_tier.record_tier("ses_unknown", waiting(AGENT_TIER="normal")) is False
    assert tab_tier.tab_tier("ses_unknown") is None
