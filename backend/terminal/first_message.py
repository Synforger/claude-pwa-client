"""launcher の agent で、 最初の発話を渡して claude を起動する。

launcher (= agent cfg `launcher: true`) の新しい会話は、 最初の発話が来るまで claude を起動しない
(= `session_resolver.resolve_launch_alias` が何も打たない)。 送信が来た時、 その pane に claude が
まだ居なければ、 本文を file に書いて `<alias> --first-message-file <file>` を打つ。 launcher が
発話を見て起動の仕方を決め、 本文を最初のメッセージとして claude に渡す (= 打鍵ではなく引数なので
複数行でも崩れない)。

階層のタブとして置いたタブ (= `SessionDef.tier_tab`、 `backend/tier_tabs/`) と、 別のタブからの連絡で始まる
会話 (= 連絡の本文からは階層が決まらないので、 タブが覚えている階層 `SessionDef.tier`、 覚えていなければ `normal`) は、 最初の発話の代わりに
その階層の封筒で起動し、 送られた本文は claude が打鍵を受け取れるようになってから次の発話として打つ
(= 本文を封筒に足すと 1 行目が client の文になり、 人が打った発話として数えられなくなる)。 自動の入れ替えの
発話は自分の階層を運ぶので、 そのまま最初の発話にする。

claude の居ない pane に届いた発話は、 そのタブに開き直せる最後の会話があれば、 新しい会話を始めずにそれを開き直して
から打つ (= 眠らせ損ねて後から終わった claude、 落ちた claude。 新しい会話で始めると、 タブの会話が黙って消える)。 新しい
会話で始めるのは、 自動の入れ替えの発話、 会話をまだ持たないタブ (= 置いたばかりの階層のタブ、 立てたばかりの子)、 ⟳ の
やり直し (= `request_fresh`) の後だけ。

「claude がまだ居ない」 は pane のプロセスで決める (= backend の記憶に頼ると、 再起動を跨いだ時に
本文が zsh へコマンドとして打たれる)。 起動を打った後は `input_ready` の旗で次の送信を待たせる
(= 起動途中の wrapper へ打鍵が流れ込まない)。

A launch stays in flight until its claude announces itself (`input_ready.launching`), however long the machine takes
to start it. While it is in flight no second launch is typed, and every message that arrives for the tab (the one the
launch was typed for included) is held here and typed in order once the claude's screen is up, each checked for
receipt (`receipt.deliver_to_woken`). Nothing is typed into a pane whose claude has not announced itself.
"""
from __future__ import annotations

import asyncio
import logging
import os
import re
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
    resume_command_for,
    uses_launcher,
)
from backend.terminal.tier import DEFAULT_TIER
from backend.tier_tabs.envelope import envelope

logger = logging.getLogger(__name__)

# launcher が claude を起動するまでの上限 (= binding 登録の探索)。 封筒で起動した後に本文を打つ前の待ちにも使う
# (= launcher は起動の前にエージェントを pull するので、 送信口の待ちの上限より長くかかる)。
LAUNCH_DISCOVER_SEC = 60.0

# The block a child tab's first message carries its tier in (= written by `tabs new`, read by the launcher).
CHILD_START = re.compile(r"^<child-start>$", re.M)

# Messages held for a tab while its launch is in flight, in the order they arrived, and the one task per tab that types
# them (= kept referenced, or it may be collected before it ends).
_held: dict[str, list[str]] = {}
_typers: dict[str, asyncio.Task] = {}

# ⟳ のやり直しで、 次の発話を新しい会話で始めるタブ (= backend の再起動を跨ぐと消え、 その時は開き直す側に倒れる)。
_fresh_requested: set[str] = set()


def request_fresh(session_id: str) -> None:
    """Start the tab's next conversation anew instead of reopening its last one (= the ⟳ restart resets the context)."""
    _fresh_requested.add(session_id)


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
    meta = sessions_meta.get(session_id)
    if meta is not None and meta.sleeping_claude_sid() is not None:
        return await _reopen_then_send(session_id, text)
    fresh = session_id in _fresh_requested
    _fresh_requested.discard(session_id)
    if meta is not None and not fresh and not _opens_a_conversation(meta, text) and resume_command_for(session_id):
        logger.info("tab without a claude: reopening its last conversation instead of starting a new one session=%s",
                    session_id)
        return await _reopen_then_send(session_id, text)
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
        _hold(session_id, text)
    return {"ok": True, "launched": True}


def hold_while_launching(session_id: str, text: str) -> dict | None:
    """Keep `text` for the tab while a launch typed into its pane is still starting, to be typed once that claude takes
    input. → the send's answer, or None when no launch is in flight (= the caller sends as usual)."""
    if not input_ready.launching(session_id):
        return None
    _hold(session_id, text)
    logger.info("launch in flight: holding the message until its claude takes input session=%s", session_id)
    return {"ok": True, "launched": True}


def _opens_a_conversation(meta, text: str) -> bool:
    """Whether `text` is meant to start a new conversation: a rollover's opening, or a child's first task."""
    return unwrap_pasted(text).lstrip().startswith(ROLLOVER_OPENING) or bool(meta.child and CHILD_START.search(text))


async def _reopen_then_send(session_id: str, text: str) -> dict:
    """The tab's pane holds a shell (= its claude did not come back when the tab woke, or it ended without the tab
    asking): reopen the tab's last conversation, and type `text` once it takes input. A first message would start a
    new conversation and the tab's conversation would not come back."""
    command = resume_command_for(session_id)
    input_ready.mark_starting(session_id)
    ok = (command is not None
          and await wait_until_typeable(session_id, input_ready.INPUT_READY_TIMEOUT_SEC)
          and tmux_send_keys(session_id, key="C-u") and tmux_send_keys(session_id, text=command, enter=True))
    if not ok:
        input_ready.mark_ready(session_id)
        logger.warning("tab without a claude: could not reopen its conversation session=%s", session_id)
        return {"ok": False, "reason": "launch_failed"}
    logger.info("tab without a claude: reopened its conversation for the first message session=%s", session_id)
    asyncio.create_task(register_claude_when_ready(session_id, max_wait=LAUNCH_DISCOVER_SEC))
    _hold(session_id, text)
    return {"ok": True, "launched": True}


def _placed_tier(session_id: str, text: str) -> str | None:
    """The tier the tab's new conversation starts in by envelope, or None when the text itself is the first
    message. A rollover and a child tab's first message (= `<child-start>`) carry their own tier, and the operator's
    words choose it in a tab not placed for a tier; a message from another tab cannot, so it starts in the tier the
    tab remembers, else its parent's (= a child works in its parent's tier), else `normal`, where the operator's
    words start when they name no tier."""
    meta = sessions_meta.get(session_id)
    if meta is None:
        return None
    opening = unwrap_pasted(text).lstrip()
    # Only a child's message may carry its tier: in any other tab, a `<child-start>` line written in a message
    # would let the sender choose the tier the receiver starts in.
    if opening.startswith(ROLLOVER_OPENING) or (meta.child and CHILD_START.search(text)):
        return None
    if meta.tier_tab is not None:
        return meta.tier_tab
    if not opening.startswith(AGENT_MESSAGE_OPENINGS):
        return None
    parent = sessions_meta.get(meta.parent_id) if meta.child and meta.parent_id else None
    return meta.tier or (parent.tier if parent is not None else None) or DEFAULT_TIER


def _hold(session_id: str, text: str) -> None:
    """Add `text` to the tab's held messages, and start the task that types them unless it runs already."""
    _held.setdefault(session_id, []).append(text)
    task = _typers.get(session_id)
    if task is None or task.done():
        task = asyncio.create_task(_type_held(session_id))
        _typers[session_id] = task
        task.add_done_callback(lambda done: _typers.pop(session_id) if _typers.get(session_id) is done else None)


async def _type_held(session_id: str) -> None:
    """Type the tab's held messages one by one, each once the launch in flight has ended and Claude's screen is up.
    A launch given up is followed by sending the held messages again, which launches anew with the first of them."""
    # routes and receipt import this module.
    from backend.terminal import receipt, routes  # noqa: PLC0415
    while _held.get(session_id):
        if not await input_ready.wait_launched(session_id):
            logger.error("launch given up: no claude announced itself in %.0fs session=%s; sending the held messages "
                         "again", input_ready.LAUNCH_GIVE_UP_SEC, session_id)
            input_ready.abandon_launch(session_id)
            for text in _held.pop(session_id, []):
                result = await routes.pty_send(session_id, {"text": text, "enter": True}, None)
                if not result.get("ok"):
                    logger.error("a held message did not go in session=%s reason=%s", session_id, result.get("reason"))
            continue
        if not await receipt.wait_for_claude_screen(session_id):
            logger.warning("held message: the screen of session=%s did not look like Claude's; typing anyway", session_id)
        text = _held[session_id].pop(0)
        try:
            taken = await receipt.deliver_to_woken(session_id, text)
        except Exception:
            # The tab may have been closed meanwhile; the next held message is still tried.
            logger.exception("a held message could not be typed session=%s", session_id)
            continue
        if not taken:
            logger.error("a held message was not taken session=%s", session_id)
    _held.pop(session_id, None)
