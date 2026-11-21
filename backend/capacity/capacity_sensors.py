"""Reads what the machine holds now, for `GET /capacity`: each tab's claude and the memory it takes, the machine's memory,
and each account's latest usage. Reads only; changes nothing. Blocking (tmux, the process table, a system call per
claude), so callers on the event loop run it in a thread.

The memory of a claude is its physical footprint (macOS `proc_pid_rusage`): the same number `footprint <pid>` prints as
`Footprint:`. The resident size is not used: it counts the program's files shared with the other claudes and memory the
system may take back, and comes out larger. On another system the footprint is not read.

Used by `routes/capacity.py`.
"""
from __future__ import annotations

import ctypes
import ctypes.util
import logging
import sys
from dataclasses import dataclass

import psutil

from backend._common import config, state
from backend.account_hold.hold_tabs import account_of
from backend.sleep.memory_sensor import read_level
from backend.terminal.pty_discover import claude_pid_in_pane
from backend.usage.usage import latest_from_tail, read_all_rate_limits_tail

logger = logging.getLogger(__name__)

MB = 1024 * 1024
#: `proc_pid_rusage`'s flavor that answers `rusage_info_v0`, the smallest one with the footprint
RUSAGE_INFO_V0 = 0
USAGE_KEYS = ("five_hour_pct", "five_hour_resets_at", "seven_day_pct", "seven_day_resets_at")


class _RusageInfoV0(ctypes.Structure):
    _fields_ = [("uuid", ctypes.c_uint8 * 16)] + [(name, ctypes.c_uint64) for name in (
        "user_time", "system_time", "pkg_idle_wkups", "interrupt_wkups", "pageins", "wired_size", "resident_size",
        "phys_footprint", "proc_start_abstime", "proc_exit_abstime")]


@dataclass(frozen=True)
class TabFacts:
    """One tab as it is now.

    id:        the tab's id
    child:     whether a tab started it to hand it work (= a child tab)
    parent_id: the tab that started it (children and forks), else None
    asleep:    whether the sleep patrol put its claude to sleep
    account:    the account it runs on
    has_claude: whether a claude runs in its pane
    claude_mb:  the footprint of that claude, None when no claude runs there (or it could not be read)
    """
    id: str
    child: bool
    parent_id: str | None
    asleep: bool
    account: str | None
    has_claude: bool
    claude_mb: float | None


@dataclass(frozen=True)
class MemoryNow:
    """The machine's memory now, in megabytes. `None` = it could not be read.

    total_mb:     the memory the machine has
    available_mb: what can be given to a new program without swapping (`psutil.virtual_memory().available`)
    level:        the operating system's memory pressure level (1 normal, 2 warning, 4 critical)
    swap_used_mb: the swap in use
    """
    total_mb: float
    available_mb: float
    level: int | None
    swap_used_mb: float


def read_tabs() -> list[TabFacts]:
    """Every Claude tab of this machine, with the claude in its pane and its footprint."""
    facts = []
    for meta in list(state.sessions_meta.values()):
        pid = claude_pid_in_pane(meta.id)
        facts.append(TabFacts(id=meta.id, child=meta.child, parent_id=meta.parent_id, asleep=meta.sleep is not None,
                              account=account_of(meta), has_claude=pid is not None,
                              claude_mb=None if pid is None else footprint_mb(pid)))
    return facts


def footprint_mb(pid: int) -> float | None:
    """The physical footprint of the process `pid` in megabytes, or None when it cannot be read (or not on macOS)."""
    if sys.platform != "darwin":
        return None
    info = _RusageInfoV0()
    try:
        library = ctypes.CDLL(ctypes.util.find_library("proc"))
        if library.proc_pid_rusage(pid, RUSAGE_INFO_V0, ctypes.byref(info)) != 0:
            return None
    except OSError:
        logger.debug("capacity: the footprint of %s could not be read", pid)
        return None
    return info.phys_footprint / MB


def read_memory_now() -> MemoryNow:
    """The machine's memory now."""
    memory = psutil.virtual_memory()
    return MemoryNow(total_mb=memory.total / MB, available_mb=memory.available / MB,
                     level=read_level() if sys.platform == "darwin" else None,
                     swap_used_mb=psutil.swap_memory().used / MB)


def read_usage() -> dict[str, dict | None]:
    """Each account of the settings → its latest usage (`five_hour_pct` / `five_hour_resets_at` / `seven_day_pct` /
    `seven_day_resets_at`), or None when no usage line was written for it."""
    rows = read_all_rate_limits_tail()
    usage = {}
    for account in config.ACCOUNTS:
        latest = latest_from_tail(rows, account_id=account)
        usage[account] = {key: latest.get(key) for key in USAGE_KEYS} if latest else None
    return usage
