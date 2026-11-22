"""`tabs capacity`: how much this machine holds now and how much room is left, before starting child tabs.

    tabs capacity [--json]
                                the child limit of the settings (none unless the operator wrote one) and this tab's children,
                                the tabs and the claudes that run, the memory a running claude takes and the machine's memory,
                                and each account's usage. Plain numbers: no line is drawn. --json prints the backend's answer

`tabs.py` reads the command word and hands the rest here with its way of calling the backend. The door is `GET /capacity`
(`backend/routes/capacity.py`); the tab that asks is `PWA_SID` (= its children are counted). A failure goes to stderr as
`tabs: <reason>` and the command ends with 1.
"""
from __future__ import annotations

import json
import os
import sys
import time
import urllib.parse
from collections.abc import Callable

USAGE = "tabs capacity [--json]"
GB = 1024.0
#: The memory pressure level of the operating system → its name (= the one Activity Monitor shows)
PRESSURE_NAMES = {1: "normal", 2: "warning", 4: "critical"}


def run(argv: list[str], call: Callable[..., tuple[int, object]]) -> int:
    """Run `tabs capacity` with `argv` (= the words after `capacity`)."""
    if argv not in ([], ["--json"]):
        print(f"usage: {USAGE}", file=sys.stderr)
        return 2
    session = os.environ.get("PWA_SID")
    status, body = call("/capacity" + (f"?{urllib.parse.urlencode({'session': session})}" if session else ""))
    if status != 200 or not isinstance(body, dict):
        detail = body.get("detail") if isinstance(body, dict) else None
        message = detail.get("message") if isinstance(detail, dict) else detail
        print(f"tabs: the capacity could not be read ({status}): {message}", file=sys.stderr)
        return 1
    print(json.dumps(body, ensure_ascii=False, indent=2) if argv else "\n".join(lines_of(body)))
    return 0


def lines_of(view: dict) -> list[str]:
    """The answer of `GET /capacity` as lines for a person or an agent to read."""
    limit = view.get("child_sessions_max")
    children = view.get("children_of_caller")
    tabs = view.get("tabs") or {}
    memory = view.get("memory") or {}
    claude = view.get("claude_mb")
    level = memory.get("pressure_level")
    lines = [
        f"machine {view.get('machine')}: child tabs "
        + ("no limit" if limit is None else f"limit {limit} per tab")
        + ("" if children is None else f" (this tab has {children})"),
        f"tabs {tabs.get('total')}: claude running {tabs.get('with_claude')}, asleep {tabs.get('asleep')}, "
        f"no claude {tabs.get('without_claude')} (children {tabs.get('children')})",
        f"memory: {_gb(memory.get('available_mb'))} available of {_gb(memory.get('total_mb'))}, pressure "
        + ("unknown" if level is None else f"{level} ({PRESSURE_NAMES.get(level, '?')})")
        + f", swap {_gb(memory.get('swap_used_mb'))} used",
    ]
    if claude:
        lines.append(f"a running claude takes {claude['median']:.0f} MB (median of {claude['count']}; "
                     f"{claude['min']:.0f}-{claude['max']:.0f} MB), so the available memory holds about "
                     f"{view.get('claudes_fitting_available')} more")
    for account in view.get("accounts") or []:
        used = _used(account.get("usage") or {}, time.time())
        lines.append(f"account {account.get('id')}: {used}; claude running {account.get('tabs_with_claude')}")
    return lines


def _used(usage: dict, now: float) -> str:
    """The windows that have a figure and have not reset. A window the account does not have is not named."""
    parts = []
    for name, field in (("5h", "five_hour"), ("7d", "seven_day")):
        pct, resets_at = usage.get(f"{field}_pct"), usage.get(f"{field}_resets_at")
        if not isinstance(pct, (int, float)) or (resets_at and resets_at <= now):
            continue
        parts.append(f"{name} {_pct(pct)} (resets {_at(resets_at or None)})")
    return ", ".join(parts) or "no usage yet"


def _gb(megabytes: float | None) -> str:
    return "?" if megabytes is None else f"{megabytes / GB:.1f} GB"


def _pct(value: float | None) -> str:
    return "?" if value is None else f"{value:.0f}%"


def _at(epoch_sec: float | None) -> str:
    return "?" if not isinstance(epoch_sec, (int, float)) else time.strftime("%m-%d %H:%M", time.localtime(epoch_sec))
