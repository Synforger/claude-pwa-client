"""Reading how short of memory the machine is (`sleep/memory_sensor.py`): the pressure level and the swap read back
since the previous look, from `vm_stat`'s page count."""
from __future__ import annotations

import subprocess

import pytest

from backend.sleep import memory_sensor as m

VM_STAT = """Mach Virtual Memory Statistics: (page size of 16384 bytes)
Pages free:                               12345.
Swapins:                                  {swapins}.
Swapouts:                                 99.
"""


@pytest.fixture(autouse=True)
def _darwin(monkeypatch):
    monkeypatch.setattr(m.sys, "platform", "darwin")
    monkeypatch.setattr(m, "_last_swapins", None)
    monkeypatch.setattr(m, "_read_level", lambda: 2)


def _vm_stat(monkeypatch, *outputs: str) -> None:
    queue = list(outputs)
    monkeypatch.setattr(m.subprocess, "run", lambda *_a, **_k: subprocess.CompletedProcess([], 0, queue.pop(0), ""))


def test_the_swap_read_back_is_the_page_count_since_the_previous_look_times_the_page_size(monkeypatch):
    _vm_stat(monkeypatch, VM_STAT.format(swapins=1000), VM_STAT.format(swapins=1064))
    first, second = m.read_memory(), m.read_memory()
    assert first.level == 2 and first.swapins_mb is None
    assert second.swapins_mb == 1.0                     # 64 pages of 16 KB


def test_a_count_that_went_down_starts_over(monkeypatch):
    _vm_stat(monkeypatch, VM_STAT.format(swapins=5000), VM_STAT.format(swapins=10))
    m.read_memory()
    assert m.read_memory().swapins_mb is None


def test_vm_stat_that_cannot_run_leaves_the_swap_unknown(monkeypatch):
    def fail(*_a, **_k):
        raise OSError("no vm_stat")
    monkeypatch.setattr(m.subprocess, "run", fail)
    assert m.read_memory().swapins_mb is None


def test_another_system_reads_nothing(monkeypatch):
    monkeypatch.setattr(m.sys, "platform", "linux")
    assert m.read_memory() == m.MemoryFacts()
