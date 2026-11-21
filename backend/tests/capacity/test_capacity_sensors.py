"""`backend/capacity/capacity_sensors.py`: the footprint and the memory are read from the real machine."""
from __future__ import annotations

import os
import sys

import pytest

from backend.capacity import capacity_sensors


@pytest.mark.skipif(sys.platform != "darwin", reason="the footprint is read on macOS only")
def test_the_footprint_of_a_running_process_is_read():
    footprint = capacity_sensors.footprint_mb(os.getpid())
    assert footprint is not None and footprint > 1.0


def test_a_process_that_is_not_there_has_no_footprint():
    assert capacity_sensors.footprint_mb(2 ** 30) is None


def test_the_memory_of_the_machine_is_read():
    memory = capacity_sensors.read_memory_now()
    assert memory.total_mb > memory.available_mb > 0 and memory.swap_used_mb >= 0
    if sys.platform == "darwin":
        assert memory.level in (1, 2, 4)
