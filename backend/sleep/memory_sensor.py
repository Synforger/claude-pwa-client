"""Reads how short of memory the machine is, for the sleep patrol: the operating system's own memory pressure level,
how much was read back from swap since the last look, and how much swap is in use. Blocking (a system call and a
`vm_stat` run); callers on the event loop run it in a thread.

The level is the one Activity Monitor's memory pressure shows (macOS `kern.memorystatus_vm_pressure_level`: 1 normal,
2 warning, 4 critical). The swap-ins are `vm_stat`'s `Swapins` page count; `psutil.swap_memory().sin` is not used,
since on macOS it counts every page-in (files included), not swap. On another system nothing is read, and the machine
counts as not short of memory.

Used by `sleep_patrol.py`.
"""
from __future__ import annotations

import ctypes
import ctypes.util
import logging
import re
import subprocess
import sys
from dataclasses import dataclass

import psutil

logger = logging.getLogger(__name__)

PRESSURE_LEVEL_NAME = b"kern.memorystatus_vm_pressure_level"
VM_STAT_TIMEOUT_SEC = 5.0
_PAGE_SIZE = re.compile(r"page size of (\d+) bytes")
_SWAPINS = re.compile(r"^Swapins:\s+(\d+)\.?$", re.M)

# The swap-in page count seen on the previous look (= the look's amount is the difference).
_last_swapins: int | None = None


@dataclass(frozen=True)
class MemoryFacts:
    """What was read about the machine's memory. `None` = it could not be read.

    level:        the operating system's memory pressure level (1 normal, 2 warning, 4 critical)
    swapins_mb:   megabytes read back from swap since the previous look (None on the first look)
    swap_used_mb: megabytes of swap in use
    """
    level: int | None = None
    swapins_mb: float | None = None
    swap_used_mb: float | None = None


def read_memory() -> MemoryFacts:
    """The machine's memory pressure level and the swap read back since the previous call. Blocking."""
    global _last_swapins
    if sys.platform != "darwin":
        return MemoryFacts()
    swapins = _read_swapins()
    since = None
    if swapins is not None and _last_swapins is not None and swapins[0] >= _last_swapins:
        since = (swapins[0] - _last_swapins) * swapins[1] / (1024 * 1024)
    _last_swapins = swapins[0] if swapins is not None else None
    return MemoryFacts(level=_read_level(), swapins_mb=since, swap_used_mb=psutil.swap_memory().used / (1024 * 1024))


def _read_level() -> int | None:
    try:
        libc = ctypes.CDLL(ctypes.util.find_library("c"))
        value = ctypes.c_int(0)
        size = ctypes.c_size_t(ctypes.sizeof(value))
        if libc.sysctlbyname(PRESSURE_LEVEL_NAME, ctypes.byref(value), ctypes.byref(size), None, 0) != 0:
            return None
    except OSError:
        logger.debug("sleep: the memory pressure level could not be read")
        return None
    return value.value


def _read_swapins() -> tuple[int, int] | None:
    """`vm_stat`'s swap-in page count and the page size."""
    try:
        out = subprocess.run(["vm_stat"], capture_output=True, text=True, timeout=VM_STAT_TIMEOUT_SEC,
                             check=True).stdout
    except (OSError, subprocess.SubprocessError):
        logger.debug("sleep: vm_stat could not be read")
        return None
    page, swapins = _PAGE_SIZE.search(out), _SWAPINS.search(out)
    if page is None or swapins is None:
        return None
    return int(swapins.group(1)), int(page.group(1))
