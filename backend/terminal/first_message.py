"""launcher の agent で、 最初の発話を渡して claude を起動する。

launcher (= agent cfg `launcher: true`) の新しい会話は、 最初の発話が来るまで claude を起動しない
(= `session_resolver.resolve_launch_alias` が何も打たない)。 送信が来た時、 その pane に claude が
まだ居なければ、 本文を file に書いて `<alias> --first-message-file <file>` を打つ。 launcher が
発話を見て起動の仕方を決め、 本文を最初のメッセージとして claude に渡す (= 打鍵ではなく引数なので
複数行でも崩れない)。

「claude がまだ居ない」 は pane のプロセスで決める (= backend の記憶に頼ると、 再起動を跨いだ時に
本文が zsh へコマンドとして打たれる)。 起動を打った後は `input_ready` の旗で次の送信を待たせる
(= 起動途中の wrapper へ打鍵が流れ込まない)。
"""
from __future__ import annotations

import asyncio
import logging
import os
import uuid
from pathlib import Path

from backend.terminal import input_ready
from backend.terminal.pty_discover import claude_in_pane, register_claude_when_ready
from backend.terminal.runner import tmux_send_keys
from backend.terminal.session_resolver import (
    ensure_pty_session_for,
    first_message_command,
    uses_launcher,
)

logger = logging.getLogger(__name__)

# launcher が claude を起動するまでの上限 (= binding 登録の探索)。
LAUNCH_DISCOVER_SEC = 60.0


def _uploads_dir() -> Path:
    from backend.config import UPLOADS_TMP  # noqa: PLC0415
    return UPLOADS_TMP


def _message_file(session_id: str, text: str) -> Path:
    """本文を本人だけが読める file に書く (= launcher が読んだら消す)。"""
    folder = _uploads_dir()
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"first-message-{session_id}-{uuid.uuid4().hex}.txt"
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        fh.write(text)
    return path


async def launch_with_first_message(session_id: str, text: str) -> dict | None:
    """claude がまだ居ない launcher の pane なら、 text を最初の発話として起動して結果を返す。
    対象外 (= launcher でない / 起動中 / 既に claude が居る) は None (= 呼び手は通常の送信へ)。"""
    if not uses_launcher(session_id):
        return None
    await ensure_pty_session_for(session_id)
    if not input_ready.is_ready(session_id) or claude_in_pane(session_id):
        return None
    command = first_message_command(session_id, _message_file(session_id, text))
    input_ready.mark_starting(session_id)
    # 入力行に残った打ちかけ (= 前の失敗の残り) を消してから打つ。
    ok = tmux_send_keys(session_id, key="C-u") and tmux_send_keys(session_id, text=command, enter=True)
    if not ok:
        input_ready.mark_ready(session_id)
        logger.warning("first message launch failed session=%s", session_id)
        return {"ok": False, "reason": "launch_failed"}
    logger.info("first message launch session=%s", session_id)
    asyncio.create_task(register_claude_when_ready(session_id, max_wait=LAUNCH_DISCOVER_SEC))
    return {"ok": True, "launched": True}
