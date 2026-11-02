"""launcher の agent で、 最初の発話を渡して claude を起動する。

launcher (= agent cfg `launcher: true`) の新しい会話は、 最初の発話が来るまで claude を起動しない
(= `session_resolver.resolve_launch_alias` が何も打たない)。 送信が来た時、 その pane に claude が
まだ居なければ、 本文を file に書いて `<alias> --first-message-file <file>` を打つ。 launcher が
発話を見て起動の仕方を決め、 本文を最初のメッセージとして claude に渡す (= 打鍵ではなく引数なので
複数行でも崩れない)。

階層のタブとして置いたタブ (= `SessionDef.tier_tab`、 `backend/tier_tabs/`) と、 別のタブからの連絡で始まる
会話 (= 連絡の本文からは階層が決まらないので、 タブが覚えている階層 `SessionDef.tier`) は、 最初の発話の代わりに
その階層の封筒で起動し、 送られた本文は claude が打鍵を受け取れるようになってから次の発話として打つ
(= 本文を封筒に足すと 1 行目が client の文になり、 人が打った発話として数えられなくなる)。 自動の入れ替えの
発話は自分の階層を運ぶので、 そのまま最初の発話にする。

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

from backend._common.state import sessions_meta
from backend.jsonl.jsonl_predicates import AGENT_MESSAGE_OPENINGS, ROLLOVER_OPENING, unwrap_pasted
from backend.terminal import input_ready
from backend.terminal.pty_discover import claude_in_pane, register_claude_when_ready
from backend.terminal.runner import tmux_send_keys, wait_until_typeable
from backend.terminal.session_resolver import (
    ensure_pty_session_for,
    first_message_command,
    uses_launcher,
)
from backend.tier_tabs.envelope import envelope

logger = logging.getLogger(__name__)

# launcher が claude を起動するまでの上限 (= binding 登録の探索)。 封筒で起動した後に本文を打つ前の待ちにも使う
# (= launcher は起動の前にエージェントを pull するので、 送信口の待ちの上限より長くかかる)。
LAUNCH_DISCOVER_SEC = 60.0

# 封筒で起動した後に本文を打つ task (= 参照を持たないと、 終わる前に回収されることがある)。
_following: set[asyncio.Task] = set()


def _uploads_dir() -> Path:
    from backend._common.config import UPLOADS_TMP  # noqa: PLC0415
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
    tier = _placed_tier(session_id, text)
    first = envelope(tier) if tier is not None else text
    command = first_message_command(session_id, _message_file(session_id, first))
    input_ready.mark_starting(session_id)
    # 立て直した直後の pane (= 自動の入れ替え) は、 tmux が session を作り終えるまで打鍵を受けない。
    # 入力行に残った打ちかけ (= 前の失敗の残り) を消してから打つ。
    ok = (await wait_until_typeable(session_id, input_ready.INPUT_READY_TIMEOUT_SEC)
          and tmux_send_keys(session_id, key="C-u") and tmux_send_keys(session_id, text=command, enter=True))
    if not ok:
        input_ready.mark_ready(session_id)
        logger.warning("first message launch failed session=%s", session_id)
        return {"ok": False, "reason": "launch_failed"}
    logger.info("first message launch session=%s tier_tab=%s", session_id, tier)
    asyncio.create_task(register_claude_when_ready(session_id, max_wait=LAUNCH_DISCOVER_SEC))
    if tier is not None:
        task = asyncio.create_task(_send_when_ready(session_id, text))
        _following.add(task)
        task.add_done_callback(_following.discard)
    return {"ok": True, "launched": True}


def _placed_tier(session_id: str, text: str) -> str | None:
    """The tier the tab's new conversation starts in by envelope, or None when the text itself is the first
    message. A rollover carries its own tier, and the operator's words choose it in a tab not placed for a tier;
    a message from another tab cannot, so it starts in the tier the tab remembers."""
    meta = sessions_meta.get(session_id)
    if meta is None:
        return None
    opening = unwrap_pasted(text).lstrip()
    if opening.startswith(ROLLOVER_OPENING):
        return None
    if meta.tier_tab is not None:
        return meta.tier_tab
    return meta.tier if opening.startswith(AGENT_MESSAGE_OPENINGS) else None


async def _send_when_ready(session_id: str, text: str) -> None:
    """Type `text` as the next message once the claude started by the envelope takes input."""
    from backend.terminal.routes import pty_send  # noqa: PLC0415  (= routes imports this module)
    if not await input_ready.wait_ready(session_id, LAUNCH_DISCOVER_SEC):
        logger.warning("tier tab: claude did not take input in %ds session=%s", LAUNCH_DISCOVER_SEC, session_id)
    result = await pty_send(session_id, {"text": text, "enter": True}, None)
    if not result.get("ok"):
        logger.error("tier tab: the message after the envelope did not go in session=%s reason=%s",
                     session_id, result.get("reason"))
