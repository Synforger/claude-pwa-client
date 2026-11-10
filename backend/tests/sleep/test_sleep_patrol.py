"""The sleep patrol (`sleep/sleep_patrol.py`): a tab seen awake again starts its quiet time over, and each look puts to
sleep the quiet tabs, the children that reported their work done and, while the machine is short of memory, the
quietest tab of those past the shorter minutes."""
from __future__ import annotations

import dataclasses
import time

import backend.sleep.sleep_patrol as patrol
import backend.sleep.sleep_sensors as sensors
from backend._common.state import SleepMark, register_session
from backend.sleep import sleep_judgement as j
from backend.sleep.memory_sensor import MemoryFacts
from backend.sleep.record_facts import RecordFacts
from backend.tests.async_run import run


def _asleep(isolated_state):
    tab = register_session("agent_a", title="T")
    tab.sleep = SleepMark(claude_sid="abc", record="/nonexistent/abc.jsonl", slept_at=int(time.time()) - 3600)
    return tab


def test_a_tab_whose_claude_runs_again_loses_its_mark_and_its_quiet_time_starts_over(isolated_state, monkeypatch):
    tab = _asleep(isolated_state)
    monkeypatch.setattr(patrol.input_ready, "is_ready", lambda _sid: True)
    monkeypatch.setattr(patrol, "claude_pid_in_pane", lambda _sid: 4242)
    monkeypatch.setattr(patrol.jsonl_watcher, "get_jsonl_for", lambda _sid: None)
    sensors._woken_at.pop(tab.id, None)
    before = time.time()
    run(patrol._clear_when_awake(tab))
    try:
        assert tab.sleep is None
        assert before <= sensors._woken_at[tab.id] <= time.time()
    finally:
        sensors._woken_at.pop(tab.id, None)


def test_a_tab_whose_claude_has_not_come_up_keeps_its_mark_and_has_no_wake_time(isolated_state, monkeypatch):
    tab = _asleep(isolated_state)
    monkeypatch.setattr(patrol.input_ready, "is_ready", lambda _sid: True)
    monkeypatch.setattr(patrol, "claude_pid_in_pane", lambda _sid: None)
    sensors._woken_at.pop(tab.id, None)
    run(patrol._clear_when_awake(tab))
    assert tab.sleep is not None and tab.id not in sensors._woken_at


# --- the look over every tab: ordinary sleeps, reported children and the pressure of memory -------------------------

AWAKE = j.SleepFacts(
    claude_running=True, starting=False, turn_open=False, record_found=True, quiet_minutes=0.0, context_pct=20,
    rollover_idle_pct=40, foreign_processes=(), record=RecordFacts(), on_voice_call=False, rolling_over=False,
    answered_since_start=True, account_pending=False,
)


class Patrol:
    """The patrol with every read replaced: the quiet minutes of each tab, whether it is a reported child, the agent's
    sleep settings and the machine's memory. The tabs put to sleep are recorded."""

    def __init__(self, monkeypatch, quiet: dict[str, float], *, reported=(), pressure=10, levels=(1,)):
        self.quiet, self.slept, self.levels = quiet, [], list(levels)
        self.reported = set(reported)
        monkeypatch.setattr(patrol, "sessions_meta", {sid: _Meta(sid) for sid in quiet})
        monkeypatch.setattr(patrol, "sleep_minutes", lambda _sid: 60)
        monkeypatch.setattr(patrol, "pressure_minutes", lambda _sid: pressure)
        monkeypatch.setattr(patrol, "_has_reported", lambda meta: meta.id in self.reported)
        monkeypatch.setattr(patrol, "_record_of", lambda _sid: RecordFacts())
        monkeypatch.setattr(patrol, "gather", lambda sid, *_args: dataclasses.replace(AWAKE, quiet_minutes=quiet[sid]))
        monkeypatch.setattr(patrol, "read_memory", lambda: MemoryFacts(level=self.levels.pop(0) if self.levels else 1))
        monkeypatch.setattr(patrol, "_last_memory", MemoryFacts())

        async def put_to_sleep(sid, minutes, **flags):
            self.slept.append((sid, minutes, tuple(sorted(name for name, on in flags.items() if on))))
            return True
        monkeypatch.setattr(patrol, "put_to_sleep", put_to_sleep)

    def look(self) -> list[tuple]:
        self.slept = []
        run(patrol.tick())
        return self.slept


@dataclasses.dataclass
class _Meta:
    id: str
    sleep: object = None


def test_a_tab_quiet_for_the_agent_s_minutes_sleeps_and_a_shorter_one_does_not(monkeypatch):
    look = Patrol(monkeypatch, {"a": 61.0, "b": 30.0})
    assert look.look() == [("a", 60, ())]


def test_a_reported_child_sleeps_after_a_few_quiet_minutes(monkeypatch):
    look = Patrol(monkeypatch, {"child": float(j.REPORTED_QUIET_MINUTES), "other": 6.0}, reported={"child"})
    assert look.look() == [("child", j.REPORTED_QUIET_MINUTES, ("reported",))]


def test_short_of_memory_on_two_looks_puts_only_the_quietest_tab_to_sleep(monkeypatch):
    look = Patrol(monkeypatch, {"a": 12.0, "b": 45.0, "c": 5.0}, levels=(2, 2))
    assert look.look() == []                                  # one high reading is not enough
    assert look.look() == [("b", 10, ("pressure",))]          # the quietest of those past the shorter minutes


def test_without_pressure_minutes_no_tab_sleeps_sooner(monkeypatch):
    look = Patrol(monkeypatch, {"a": 45.0}, pressure=None, levels=(4, 4))
    look.look()
    assert look.look() == []


def test_a_change_of_the_memory_level_is_written_to_the_log(monkeypatch, caplog):
    look = Patrol(monkeypatch, {"a": 1.0}, levels=(1, 1, 2))
    caplog.set_level("INFO", logger="backend.sleep.sleep_patrol")
    for _ in range(3):
        look.look()
    lines = [r.getMessage() for r in caplog.records if r.getMessage().startswith("sleep: memory")]
    assert [line.split()[2] for line in lines] == ["level=1", "level=2"]
