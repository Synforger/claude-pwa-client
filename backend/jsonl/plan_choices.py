"""ExitPlanMode の承認選択肢を tmux 画面から抽出する。

claude TUI は ExitPlanMode tool_use を JSONL に書いた直後に terminal に承認 prompt
(「1. Yes, ... / 2. ... / 3. ...」) を描画するので、 数百 ms 待ってから tmux capture-pane
で拾うことで PWA 側で PlanApprovalBubble を構築できる (= 抽出失敗時は frontend 側の
fallback で固定 2 択にフォールバック)。
"""
from __future__ import annotations

import asyncio
import re

from backend.terminal.runner import capture_tmux_scrollback
from backend.state import agent_status, stream_states


# ANSI escape を剥がして plain text にする (= tmux capture-pane の出力に色 / cursor 制御が
# 含まれる、 選択肢抽出時にノイズ)
_ANSI_RE = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]|\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)|\x1b[@-Z\\-_]")
# 「1. Yes, auto-accept edits」 みたいな choice 行を拾う
_PLAN_CHOICE_RE = re.compile(r"^\s*(\d+)\.\s+(.+?)\s*$", re.MULTILINE)


def _strip_ansi(s: str) -> str:
    return _ANSI_RE.sub("", s)


# 選択肢抽出 polling のパラメータ (= backend-F-13)。 旧版は固定 0.5s 待ってから 1 回
# capture していたが、 claude TUI の prompt 描画が早く済むケース (= 50-150ms) でも
# 強制 500ms 待ち合わせていた。 100ms × 最大 10 回 polling で早期確定させる
# (= 抽出 OK 即 return、 上限到達まで失敗なら fallback の固定 2 択へ)。
_POLL_INTERVAL_S = 0.1
_POLL_MAX_ATTEMPTS = 10


def _extract_choices_from_pane(text: str) -> list[dict]:
    """tmux scrollback テキスト (= ANSI 除去済) から末尾の連続番号付き選択肢を抽出する。
    旧 capture_plan_choices インライン処理を pure 関数に切り出して polling 内で再利用する。"""
    choices: list[dict] = []
    seen_keys: set[str] = set()
    for m in _PLAN_CHOICE_RE.finditer(text):
        key, label = m.group(1), m.group(2)
        if key in seen_keys:
            continue
        seen_keys.add(key)
        # label 末尾の「 (esc to interrupt)」 等の補助文言を捨てる
        label = label.split("(")[0].strip()
        if label:
            choices.append({"key": key, "label": label})
    if len(choices) >= 2:
        # 末尾から「N, N-1, N-2 ...」 と降順で連続するブロックだけ採用
        tail: list[dict] = []
        for c in reversed(choices):
            if not tail:
                tail.append(c)
                continue
            prev_key = int(tail[-1]["key"])
            if int(c["key"]) == prev_key - 1:
                tail.append(c)
            else:
                break
        tail.reverse()
        choices = tail
    return choices


async def capture_plan_choices(session_id: str, tool_use_id: str) -> None:
    """ExitPlanMode tool_use 直後に tmux 画面を capture して選択肢テキストを抽出する。

    backend-F-13: 旧 0.5s 固定 sleep を 100ms × 10 回 polling に変更。 prompt 描画が
    早いケースで体感を ~400ms 短縮する。 choices >= 2 確定で即 return、 上限到達まで
    失敗なら何もせず終了 (= frontend が fallback の固定 2 択 (1=Approve / 3=No) を出す)。
    """
    a = agent_status.get(session_id)
    if a is None:
        return
    for _ in range(_POLL_MAX_ATTEMPTS):
        await asyncio.sleep(_POLL_INTERVAL_S)
        pending = a.get("pending_plan")
        if not pending or pending.get("tool_use_id") != tool_use_id:
            return  # 既に resolved or 別 plan に上書き
        try:
            raw = capture_tmux_scrollback(session_id, lines=120)
        except Exception:
            raw = b""
        if not raw:
            continue
        text = _strip_ansi(raw.decode("utf-8", errors="replace"))
        choices = _extract_choices_from_pane(text)
        # 連続番号 >= 2 が取れたら確定。 取れなければ次 tick で再試行 (TUI 描画待ち)。
        if len(choices) >= 2:
            pending = a.get("pending_plan")
            if pending and pending.get("tool_use_id") == tool_use_id:
                a["pending_plan"] = {**pending, "choices": choices}
                state = stream_states.get(session_id)
                if state is not None:
                    state.status_event.set()
            return
