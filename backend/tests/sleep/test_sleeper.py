"""Putting a tab's claude to sleep (`sleep/sleeper.py`) and waking it. Neither tmux nor claude is started: a plain
process stands in for the claude, and the terminal calls are recorded."""
from __future__ import annotations

import asyncio
import dataclasses
import json
import signal
import subprocess
import sys

import pytest

from backend.sleep import sleep_judgement as j
from backend.sleep import sleeper
from backend.sleep.record_facts import RecordFacts
from backend.terminal import session_resolver

READY = j.SleepFacts(
    claude_running=True, starting=False, turn_open=False, record_found=True, quiet_minutes=75.0, context_pct=22,
    rollover_idle_pct=40, foreign_processes=(), record=RecordFacts(), on_voice_call=False, rolling_over=False,
)


def _run(coro):
    return asyncio.run(coro)


def _claude(script: str = "pass") -> subprocess.Popen:
    """A process standing in for the claude of a tab; returns once it runs."""
    process = subprocess.Popen(
        [sys.executable, "-c", f"import signal, time; {script}; print(flush=True); time.sleep(60)"],
        stdout=subprocess.PIPE)
    process.stdout.readline()
    return process


class World:
    """The terminal side of one tab, recorded."""

    def __init__(self, monkeypatch, isolated_state, tmp_path, claude: subprocess.Popen, *, facts=READY, tail=b"\n"):
        from backend._common.state import register_session  # noqa: PLC0415
        self.meta = register_session("agent_a", "sleeper")
        self.events: list[str] = []
        self.claude = claude
        self.record = tmp_path / "7a1c9e2e-1111-2222-3333-444455556666.jsonl"
        self.record.write_bytes(json.dumps({"type": "user", "message": {"content": "go"}}).encode() + tail)
        self.facts = facts

        def kill_session(sid):
            # the terminal is closed only once the claude is gone
            self.events.append(f"kill-session claude_alive={claude.poll() is None}")
            return True

        monkeypatch.setattr(sleeper, "gather", lambda sid, minutes, by_hand=False: self.facts)
        monkeypatch.setattr(sleeper.jsonl_watcher, "get_jsonl_for", lambda sid: self.record)
        monkeypatch.setattr(sleeper, "claude_pid_in_pane", lambda sid: claude.pid)
        monkeypatch.setattr(sleeper, "kill_tmux_session", kill_session)
        monkeypatch.setattr(sleeper, "EXIT_WAIT_SEC", 1.0)
        sleeper.pty_sessions.pop(self.meta.id, None)


def test_a_quiet_tab_sleeps_with_its_conversation_kept_and_its_terminal_gone(monkeypatch, isolated_state, tmp_path, caplog):
    claude = _claude()
    world = World(monkeypatch, isolated_state, tmp_path, claude)
    caplog.set_level("INFO", logger="backend.sleep.sleeper")

    assert _run(sleeper.put_to_sleep(world.meta.id, 60)) is True

    assert claude.poll() is not None                                  # the claude ended, by itself, on the request
    assert world.events == ["kill-session claude_alive=False"]        # and only then was the terminal closed
    mark = world.meta.sleep
    assert (mark.claude_sid, mark.record) == ("7a1c9e2e-1111-2222-3333-444455556666", str(world.record))
    stored = json.loads(isolated_state.SESSION_META_PATH.read_text())
    assert stored[0]["sleep"]["claude_sid"] == mark.claude_sid       # it survives a restart of the backend
    assert f"sleep: session={world.meta.id} claude_sid={mark.claude_sid} idle_min=75 context_pct=22" in caplog.text
    claude.stdout.close()


def test_the_next_start_of_a_sleeping_tab_reopens_the_same_conversation(monkeypatch, isolated_state, tmp_path):
    claude = _claude()
    world = World(monkeypatch, isolated_state, tmp_path, claude)
    _run(sleeper.put_to_sleep(world.meta.id, 60))
    monkeypatch.setattr(session_resolver, "CLAUDE_PATH", "/usr/local/bin/claude")
    monkeypatch.setattr(session_resolver, "resolve_agent_cfg", lambda _sid: {"launch_alias": "agent_a"})
    # whatever the bindings say (= gone, or another conversation), the saved id is the one that is opened
    monkeypatch.setattr(session_resolver, "last_resumable_claude_sid", lambda _sid: None)
    command = session_resolver.resolve_launch_alias(world.meta.id)
    assert command == "/usr/local/bin/claude --resume 7a1c9e2e-1111-2222-3333-444455556666"
    assert session_resolver.resume_command_for(world.meta.id) == command
    assert session_resolver.resolve_autoresume_fallback(world.meta.id) is None   # no new conversation in its place
    claude.stdout.close()


def test_a_launcher_agent_reopens_through_its_launcher(monkeypatch, isolated_state, tmp_path):
    claude = _claude()
    world = World(monkeypatch, isolated_state, tmp_path, claude)
    _run(sleeper.put_to_sleep(world.meta.id, 60))
    monkeypatch.setattr(session_resolver, "resolve_agent_cfg", lambda _sid: {"launch_alias": "main", "launcher": True})
    monkeypatch.setattr(session_resolver, "last_resumable_claude_sid", lambda _sid: None)
    assert session_resolver.resolve_launch_alias(world.meta.id) == \
        "main --resume 7a1c9e2e-1111-2222-3333-444455556666"
    claude.stdout.close()


def test_a_claude_that_does_not_end_is_left_awake_and_its_terminal_stays(monkeypatch, isolated_state, tmp_path, caplog):
    monkeypatch.setattr(sleeper, "EXIT_WAIT_SEC", 0.3)
    claude = _claude("signal.signal(signal.SIGTERM, signal.SIG_IGN)")
    world = World(monkeypatch, isolated_state, tmp_path, claude)
    monkeypatch.setattr(sleeper, "EXIT_WAIT_SEC", 0.3)
    caplog.set_level("INFO", logger="backend.sleep.sleeper")

    assert _run(sleeper.put_to_sleep(world.meta.id, 60)) is False

    assert claude.poll() is None                      # not killed
    assert world.events == []                         # the terminal was not closed
    assert world.meta.sleep is None                   # and the tab does not claim to be asleep
    assert json.loads(isolated_state.SESSION_META_PATH.read_text())[0]["sleep"] is None
    assert "left awake" in caplog.text
    claude.kill()
    claude.wait()
    claude.stdout.close()


@pytest.mark.parametrize("change", [
    {"turn_open": True}, {"quiet_minutes": 3.0}, {"foreign_processes": ("zsh",)},
    {"record": RecordFacts(wakeup_pending=True)}, {"on_voice_call": True}, {"rolling_over": True},
])
def test_a_condition_that_fails_at_the_last_look_stops_the_sleep(monkeypatch, isolated_state, tmp_path, change):
    claude = _claude()
    world = World(monkeypatch, isolated_state, tmp_path, claude, facts=dataclasses.replace(READY, **change))
    assert _run(sleeper.put_to_sleep(world.meta.id, 60)) is False
    assert claude.poll() is None and world.events == [] and world.meta.sleep is None
    claude.kill()
    claude.wait()
    claude.stdout.close()


def test_a_record_that_ends_in_a_partial_line_is_not_slept_on(monkeypatch, isolated_state, tmp_path):
    claude = _claude()
    world = World(monkeypatch, isolated_state, tmp_path, claude, tail=b"")
    assert _run(sleeper.put_to_sleep(world.meta.id, 60)) is False
    assert claude.poll() is None and world.meta.sleep is None
    claude.kill()
    claude.wait()
    claude.stdout.close()


def test_a_record_that_is_gone_is_not_slept_on(monkeypatch, isolated_state, tmp_path):
    claude = _claude()
    world = World(monkeypatch, isolated_state, tmp_path, claude)
    world.record.unlink()
    assert _run(sleeper.put_to_sleep(world.meta.id, 60)) is False
    assert claude.poll() is None and world.meta.sleep is None
    claude.kill()
    claude.wait()
    claude.stdout.close()


def test_a_tab_that_moved_to_another_account_does_not_reopen_the_old_conversation(monkeypatch, isolated_state, tmp_path):
    claude = _claude()
    world = World(monkeypatch, isolated_state, tmp_path, claude)
    _run(sleeper.put_to_sleep(world.meta.id, 60))
    world.meta.account_id = "company"
    world.meta.resume_session_id = "moved-lineage"
    monkeypatch.setattr(session_resolver, "CLAUDE_PATH", "/usr/local/bin/claude")
    monkeypatch.setattr(session_resolver, "resolve_agent_cfg", lambda _sid: {"launch_alias": "agent_a"})
    assert session_resolver.resolve_launch_alias(world.meta.id) == "/usr/local/bin/claude --resume moved-lineage"
    claude.stdout.close()


def test_a_restart_that_asks_for_a_fresh_conversation_gets_one(monkeypatch, isolated_state, tmp_path):
    claude = _claude()
    world = World(monkeypatch, isolated_state, tmp_path, claude)
    _run(sleeper.put_to_sleep(world.meta.id, 60))
    monkeypatch.setattr(session_resolver, "resolve_agent_cfg", lambda _sid: {"launch_alias": "agent_a"})
    assert session_resolver.resolve_launch_alias(world.meta.id, prefer_fresh=True) == "agent_a"
    claude.stdout.close()


def test_end_claude_returns_true_for_a_process_that_is_already_gone():
    process = subprocess.Popen([sys.executable, "-c", "pass"])
    process.wait()
    assert sleeper.end_claude(process.pid) is True


def test_a_sleep_mark_round_trips_through_the_tab_definition():
    from backend._common.state import SleepMark  # noqa: PLC0415
    mark = SleepMark(claude_sid="abc", record="/r/abc.jsonl", slept_at=7, account_id="company")
    assert SleepMark.from_dict(mark.to_dict()) == mark
    assert SleepMark.from_dict(None) is None
    assert SleepMark.from_dict({"claude_sid": "", "record": "x"}) is None
    assert SleepMark.from_dict({"record": "x"}) is None


# --- a parent putting its child to sleep (= `sleep_now`) ---------------------------------------------------------

def test_a_child_its_parent_puts_to_sleep_sleeps_without_the_quiet_time(monkeypatch, isolated_state, tmp_path, caplog):
    claude = _claude()
    world = World(monkeypatch, isolated_state, tmp_path, claude,
                  facts=dataclasses.replace(READY, quiet_minutes=2.0, context_pct=55))
    caplog.set_level("INFO", logger="backend.sleep.sleeper")
    assert _run(sleeper.sleep_now(world.meta.id)) == ()
    assert claude.poll() is not None and world.meta.sleep is not None
    assert "by_hand=1" in caplog.text
    claude.stdout.close()


def test_a_sleep_by_hand_waits_for_the_child_to_finish_its_answer(monkeypatch, isolated_state, tmp_path):
    claude = _claude()
    world = World(monkeypatch, isolated_state, tmp_path, claude, facts=dataclasses.replace(READY, turn_open=True))
    monkeypatch.setattr(sleeper, "PASSING_LOOK_SEC", 0.01)
    looks = []

    def gather(sid, minutes, by_hand=False):
        looks.append(by_hand)
        return world.facts if len(looks) < 3 else READY   # the answer ends at the third look

    monkeypatch.setattr(sleeper, "gather", gather)
    assert _run(sleeper.sleep_now(world.meta.id)) == ()
    assert looks == [True, True, True] and world.meta.sleep is not None
    claude.stdout.close()


def test_a_sleep_by_hand_gives_up_on_an_answer_that_does_not_end(monkeypatch, isolated_state, tmp_path):
    claude = _claude()
    world = World(monkeypatch, isolated_state, tmp_path, claude, facts=dataclasses.replace(READY, turn_open=True))
    monkeypatch.setattr(sleeper, "PASSING_WAIT_SEC", 0.05)
    monkeypatch.setattr(sleeper, "PASSING_LOOK_SEC", 0.01)
    assert _run(sleeper.sleep_now(world.meta.id)) == (j.TURN_OPEN,)
    assert claude.poll() is None and world.meta.sleep is None
    claude.kill()
    claude.wait()
    claude.stdout.close()


def test_a_sleep_by_hand_answers_at_once_for_a_condition_that_does_not_pass_by_itself(monkeypatch, isolated_state,
                                                                                         tmp_path):
    claude = _claude()
    world = World(monkeypatch, isolated_state, tmp_path, claude,
                  facts=dataclasses.replace(READY, turn_open=True, record=RecordFacts(wakeup_pending=True)))
    monkeypatch.setattr(sleeper, "PASSING_WAIT_SEC", 30.0)
    assert _run(asyncio.wait_for(sleeper.sleep_now(world.meta.id), 5)) == (j.TURN_OPEN, j.WAKEUP_SCHEDULED)
    assert claude.poll() is None and world.meta.sleep is None
    claude.kill()
    claude.wait()
    claude.stdout.close()
