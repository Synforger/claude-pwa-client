"""タブで動いている claude の記録 (= Claude Code が口座ごとに置く `sessions/*.json`) を読む。

`tabs list` (この機械のタブの状態の欄) と、 相手の機械へ返すタブの一覧 (`routes/agent_messages.py`) と、 hook が届いた会話の
claude を探す所 (`routes/hooks.py`) が使う。
同じ記録から同じ語を出すため、 読み方は 1 か所に置く。
"""
from __future__ import annotations

import json
import os
from pathlib import Path

#: Claude Code の記録に状態が書かれていない claude の状態の語。
UNKNOWN_STATUS = "?"


def alive(pid: object) -> bool:
    """その pid の process が居るか。"""
    try:
        os.kill(int(pid), 0)
    except (OSError, TypeError, ValueError):
        return False
    return True


def running_claudes() -> dict[str, dict]:
    """タブの id → そのタブで動いている claude の記録 (= `account_dir` に、 その記録を置いた口座の folder を足した物)。"""
    found = {}
    for path in Path.home().glob(".claude*/sessions/*.json"):
        try:
            row = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        tab = str(row.get("tmux") or "").split(":")[0].removeprefix("pwa-")
        if tab and row.get("sessionId") and alive(row.get("pid")):
            found[tab] = {**row, "account_dir": path.parents[1]}
    return found


def pid_of_conversation(claude_sid: str) -> int | None:
    """The pid of the running claude whose conversation is `claude_sid` (= from Claude Code's `sessions/*.json`), or None
    when no record names it."""
    for path in Path.home().glob(".claude*/sessions/*.json"):
        try:
            row = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if row.get("sessionId") == claude_sid and alive(row.get("pid")):
            return int(row["pid"])
    return None


def status_of(claude: dict | None) -> str | None:
    """動いている claude の状態の語 (= 記録の `status`。 書かれていなければ `?`)。 claude が居なければ None。"""
    return None if claude is None else str(claude.get("status") or UNKNOWN_STATUS)
