"""Type one text into a tab whose agent takes asks, and give back the last answer of that turn. Called by `routes/ask.py`.

An ask is a program's question to a Claude Code tab it uses as its model. The text goes in as plain input (= no
envelope, unlike a message from another tab), and the answer is what the `Stop` hook says the turn ended with. Plain
input is what the operator's own words look like, so only an agent with `"ask": true` in the client's configuration
takes asks: a tab set up for a program, not one an agent works in.

A turn that hits a usage limit ends without a `Stop`: the record is watched for it (`limit_watch.py`), and the ask
answers `ask_held` at once instead of waiting out its time.

An ask can first open another conversation in the tab: `resume` types `/resume <id>` and waits for that conversation's
`SessionStart`, `fork` then types `/branch` and waits for the new conversation's (= the question goes into a branch,
and the conversation it came from stays as it was).

`ask_stream` is the same ask that also hands on the answer while the turn runs: what Claude Code has drawn of it on the
screen (`screen_watch.py`), then the `Stop` hook's answer. It fails before the typing as `ask` does, and after it as an
event of the stream.
"""
from __future__ import annotations

import asyncio
import logging
import time
from collections import Counter
from collections.abc import AsyncIterator, Callable, Iterator
from contextlib import contextmanager
from typing import NamedTuple

from fastapi import HTTPException

from backend._common.errors import raise_error
from backend.account_hold import hold_mail
import backend.jsonl.jsonl_watcher as jsonl_watcher
from backend.ask import limit_watch, screen_watch, turn_waiters
from backend.routes.agent_messages import deliver_message, resolve_receiver, wake_tab
from backend.routes.overview import is_busy
from backend.terminal.pty_discover import claude_in_pane
from backend.terminal.routes import pty_send
from backend.terminal.session_resolver import takes_asks

logger = logging.getLogger(__name__)

DEFAULT_TIMEOUT_SEC = 180.0
MAX_TIMEOUT_SEC = 3600.0
#: How long a `/clear` gets to open the new conversation (= the `SessionStart` hook comes within a second or two)
CLEAR_WAIT_SEC = 30.0
CLEAR_COMMAND = "/clear"
#: How long a `/resume` or a `/branch` gets to open its conversation (= measured at about one and about four seconds)
RESUME_WAIT_SEC = 30.0
RESUME_COMMAND = "/resume"
BRANCH_COMMAND = "/branch"

#: The failures of the delivery shared with the messages between tabs (`routes/agent_messages.py`), as the asker's
#: codes. Any other code of that door means the text may have been typed: `ask_unconfirmed`.
_DELIVERY_CODES: dict[str, tuple[int, str]] = {
    "agent_message_receiver_not_running": (409, "ask_not_ready"),
    "agent_message_receiver_not_ready": (409, "ask_not_ready"),
    "agent_message_not_taken": (409, "ask_not_ready"),
    "agent_message_not_sent": (409, "ask_not_ready"),
    "agent_message_unknown_receiver": (404, "ask_unknown_tab"),
    "agent_message_ambiguous_receiver": (409, "ask_ambiguous_tab"),
    "agent_message_api_tab": (403, "ask_not_allowed"),
}


class _Turn(NamedTuple):
    """An ask whose text is typed: the tab, the text, its wait, the answer it expects and where its record began."""
    session_id: str
    text: str
    waiter: turn_waiters.TurnWaiter
    answer: asyncio.Future[str]
    since: limit_watch.RecordMark
    pasted_before: Counter[str] | None = None


async def ask(to: str, text: str, *, fresh: bool = False, resume: str | None = None, fork: bool = False,
              timeout_sec: float = DEFAULT_TIMEOUT_SEC) -> dict:
    """Ask the tab `to` (= its id or name) `text` and wait for the turn's last answer.

    `fresh` types `/clear` first, so the turn sees nothing of the asks before it. `resume` (a Claude Code conversation's
    id) opens that conversation first, and `fork` with it opens a branch of it, so the turn goes on in the branch. The
    caller has checked that they are not asked for together with `fresh` (= `routes/ask.py`). A turn that has not ended within
    `timeout_sec` of the typing is stopped (= Escape), so that the tab is free for the next ask. A turn that a usage
    limit ended answers `ask_held` with the limit's text; its question stays in the conversation.
    → `{"ok": True, "id": <tab id>, "answer": <text>, "session": <the id of the conversation the turn was in, or None>}`;
    failures are HTTP errors with an `ask_*` code."""
    turn = await _start(to, text, fresh=fresh, resume=resume, fork=fork)
    try:
        answer = await _wait(turn, timeout_sec)
    finally:
        turn_waiters.stop_waiting(turn.session_id, turn.waiter)
    return {"ok": True, "id": turn.session_id, "answer": answer, "session": turn.waiter.claude_session_id}


async def ask_stream(to: str, text: str, *, fresh: bool = False, resume: str | None = None, fork: bool = False,
                     timeout_sec: float = DEFAULT_TIMEOUT_SEC) -> AsyncIterator[dict]:
    """Ask as `ask` does, and give the events of the turn as it runs. Everything up to the typing is done when this
    returns, and fails as an HTTP error as in `ask`; the iterator then yields

    - `{"type": "partial", "text": <the answer so far, as the screen shows it>}` whenever it changed,
    - and last either `{"type": "final", "text": <the Stop hook's answer>, "session": <Claude's session id or None>}`
      or `{"type": "error", "code": "ask_*", "message": ...}` (= the failures `ask` raises after the typing).

    The tab's wait ends with the turn (= its answer, its failure or its time), whether the iterator is read or not."""
    turn = await _start(to, text, fresh=fresh, resume=resume, fork=fork, read_screen=True)
    partials: asyncio.Queue[str] = asyncio.Queue()
    watching = asyncio.ensure_future(screen_watch.watch(turn.session_id, turn.text, partials.put_nowait,
                                                        turn.pasted_before))
    waiting = asyncio.ensure_future(_wait(turn, timeout_sec))
    waiting.add_done_callback(lambda done: _release(turn, done, watching))
    return _events(turn, partials, waiting)


async def _start(to: str, text: str, *, fresh: bool, resume: str | None, fork: bool, read_screen: bool = False) -> _Turn:
    """Everything an ask does up to the typing; `read_screen` notes the placeholders on the screen right before it (=
    for `ask_stream`). → the turn, whose wait the caller ends; a failure ends it here."""
    with _as_ask_error():
        session_id = resolve_receiver(to)
    if not takes_asks(session_id):
        raise_error(403, "ask_not_allowed",
                    f"このタブのエージェントは聞かれる設定 (= \"ask\": true) を持っていません: {session_id}", id=session_id)
    waiter = turn_waiters.start_waiting(session_id)
    if waiter is None:
        raise_error(409, "ask_in_progress", f"このタブには別の問いの答えを待っています。 答えが返ってから聞いてください: {session_id}",
                    id=session_id)
    try:
        return await _type_text(session_id, text, waiter, fresh=fresh, resume=resume, fork=fork,
                                read_screen=read_screen)
    except BaseException:
        turn_waiters.stop_waiting(session_id, waiter)
        raise


async def _type_text(session_id: str, text: str, waiter: turn_waiters.TurnWaiter, *, fresh: bool, resume: str | None,
                     fork: bool, read_screen: bool = False) -> _Turn:
    if await asyncio.to_thread(hold_mail.must_keep, session_id):
        raise_error(409, "ask_held", "このタブは口座の止める線で止まっていて、 動ける口座がありません。 何も聞いていません",
                    id=session_id, reason="account_hold")
    with _as_ask_error():
        woke = await wake_tab(session_id)
    if is_busy(session_id):
        raise_error(409, "ask_tab_busy", "このタブは別の仕事の途中です。 何も聞いていません。 終わってから聞いてください", id=session_id)
    # A tab with no claude yet starts a new conversation with the text itself: there is nothing to clear.
    cleared = fresh and claude_in_pane(session_id)
    if cleared:
        await _open_conversation(session_id, waiter, CLEAR_COMMAND, lambda opened: True, CLEAR_WAIT_SEC)
    if resume is not None:
        await _open_resumed(session_id, waiter, resume, fork)
    since = await asyncio.to_thread(limit_watch.mark, session_id)
    pasted_before = await asyncio.to_thread(screen_watch.read_pasted_counts, session_id) if read_screen else None
    answer = turn_waiters.expect_answer(waiter)
    with _as_ask_error():
        await deliver_message(session_id, text, woke and not cleared)
    logger.info("ask: typed %d chars into session=%s fresh=%s resume=%s fork=%s", len(text), session_id, cleared, resume,
                fork)
    return _Turn(session_id, text, waiter, answer, since, pasted_before)


async def _wait(turn: _Turn, timeout_sec: float) -> str:
    """Wait for the turn's last answer, up to `timeout_sec` after the typing. → the answer; failures are HTTP errors."""
    session_id, since = turn.session_id, turn.since
    logger.info("ask: waiting up to %.0fs for the answer in session=%s", timeout_sec, session_id)
    limit = asyncio.ensure_future(limit_watch.wait_for_limit(session_id, since))
    try:
        done, _ = await asyncio.wait({turn.answer, limit}, timeout=timeout_sec, return_when=asyncio.FIRST_COMPLETED)
    finally:
        limit.cancel()
    if limit in done:
        await _held_by_limit(session_id, since, limit.result())
    if turn.answer in done:
        end = await limit_watch.settled_turn(session_id, since)
        if end.limit_message is not None:
            await _held_by_limit(session_id, since, end.limit_message)
        return turn.answer.result()
    stopped = await _press_escape(session_id)
    logger.warning("ask: no answer within %.0fs in session=%s; turn stopped=%s", timeout_sec, session_id, stopped)
    raise_error(504, "ask_timeout",
                f"{timeout_sec:.0f} 秒以内に答えが終わりませんでした。 "
                + ("そのターンは止めました" if stopped else "そのターンを止められませんでした"),
                id=session_id)
    raise AssertionError("unreachable")


def _release(turn: _Turn, waiting: asyncio.Future[str], watching: asyncio.Future[None]) -> None:
    """The turn's wait is over (= answered, failed, timed out or cancelled): stop reading the screen and free the tab
    for the next ask. A failure is the stream's last event (`_end_event`), so it is only taken off the task here."""
    watching.cancel()
    turn_waiters.stop_waiting(turn.session_id, turn.waiter)
    if not waiting.cancelled():
        waiting.exception()


async def _events(turn: _Turn, partials: asyncio.Queue[str], waiting: asyncio.Future[str]) -> AsyncIterator[dict]:
    """The events of `ask_stream`: a partial each time the screen's answer changes, then the end of the turn. Closing
    the iterator early gives the wait up (= the tab's turn goes on, as when a program stops waiting for an ask)."""
    next_partial: asyncio.Future[str] | None = None
    try:
        while not waiting.done():
            next_partial = next_partial or asyncio.ensure_future(partials.get())
            await asyncio.wait({next_partial, waiting}, return_when=asyncio.FIRST_COMPLETED)
            if next_partial.done():
                yield {"type": "partial", "text": next_partial.result()}
                next_partial = None
        yield _end_event(turn, waiting)
    finally:
        if next_partial is not None and not next_partial.done():
            next_partial.cancel()
        if not waiting.done():
            waiting.cancel()


def _end_event(turn: _Turn, waiting: asyncio.Future[str]) -> dict:
    """The last event of a stream: the answer, or the failure `ask` would have raised."""
    try:
        return {"type": "final", "text": waiting.result(), "session": turn.waiter.claude_session_id}
    except HTTPException as error:
        detail = error.detail if isinstance(error.detail, dict) else {}
        event = {"type": "error", "code": str(detail.get("code") or "ask_unconfirmed"),
                 "message": str(detail.get("message") or error.detail)}
        if detail.get("params"):
            event["params"] = detail["params"]
        return event


async def _held_by_limit(session_id: str, since: limit_watch.RecordMark, limit_message: str) -> None:
    """Answer the ask whose turn a usage limit ended, after cancelling the continuation Claude Code booked (= the
    program asks again; the tab carrying on by itself at the reset would take that ask's `Stop`). Always raises."""
    cancelled = await limit_watch.cancel_continuation(session_id, since, lambda: _press_escape(session_id))
    logger.warning("ask: usage limit in session=%s after %.1fs; continuation cancelled=%s", session_id,
                   time.time() - since.typed_at, cancelled)
    raise_error(409, "ask_held",
                f"このタブの口座が使用量の上限に当たり、 ターンは答えずに終わりました ({limit_message})。 "
                "問いは会話に残っています。 上限が戻ってから --fresh で聞き直してください",
                id=session_id, reason="limit_stop", limit_message=limit_message, continuation_cancelled=cancelled)


async def _press_escape(session_id: str) -> bool:
    """Press Escape in the tab. → whether the key went in."""
    return bool((await pty_send(session_id, {"key": "Escape"}, None)).get("ok"))


async def _open_resumed(session_id: str, waiter: turn_waiters.TurnWaiter, resume: str, fork: bool) -> None:
    """Open the conversation `resume` in the tab, and with `fork` a branch of it: type `/resume <id>` (not when the tab is
    in that conversation already: Claude Code has nothing to open then) and `/branch`, each waiting for the `SessionStart`
    of the conversation it opens. A conversation that does not open ends the ask: nothing was asked."""
    if not claude_in_pane(session_id):
        raise_error(409, "ask_not_ready", "このタブには Claude が居ないので、 会話を開けません。 何も聞いていません。 "
                    "--resume を付けずに 1 度聞いて Claude を起動してから聞き直してください", id=session_id)
    if _conversation_of(session_id) != resume:
        await _open_conversation(session_id, waiter, f"{RESUME_COMMAND} {resume}", lambda opened: opened == resume,
                                 RESUME_WAIT_SEC, escape=True)
    if fork:
        await _open_conversation(session_id, waiter, BRANCH_COMMAND, lambda opened: opened not in (None, resume),
                                 RESUME_WAIT_SEC, escape=True)


def _conversation_of(session_id: str) -> str | None:
    """The id of the conversation the tab is in (= the record the tab's last hook said it writes)."""
    record = jsonl_watcher.get_jsonl_for(session_id)
    return record.stem if record is not None else None


async def _open_conversation(session_id: str, waiter: turn_waiters.TurnWaiter, command: str,
                             accept: Callable[[str | None], bool], wait_sec: float, *, escape: bool = False) -> None:
    """Type `command` and wait for the `SessionStart` of the conversation it opens (= the id `accept` takes). When none
    opens, `escape` presses Escape once, so that the search a `/resume` of an unknown id leaves open does not stay on the
    tab's screen. Failures are `ask_not_ready`."""
    after = len(waiter.openings)
    result = await pty_send(session_id, {"text": command, "enter": True}, None)
    if not result.get("ok"):
        raise_error(409, "ask_not_ready", f"{command.split()[0]} を打てませんでした。 何も聞いていません。 もう一度聞いてください",
                    id=session_id)
    if not await waiter.wait_opening(after, accept, wait_sec):
        if escape:
            await _press_escape(session_id)
        raise_error(409, "ask_not_ready",
                    f"{command.split()[0]} の後、 {wait_sec:.0f} 秒以内に会話が開きませんでした。 何も聞いていません。 "
                    "もう一度聞いてください", id=session_id, command=command)


@contextmanager
def _as_ask_error() -> Iterator[None]:
    """Give a failure of the shared delivery the asker's code (= the message stays: it says what to do next)."""
    try:
        yield
    except HTTPException as error:
        detail = error.detail if isinstance(error.detail, dict) else {}
        code = str(detail.get("code") or "")
        if not code.startswith("agent_message_"):
            raise
        status, ask_code = _DELIVERY_CODES.get(code, (500, "ask_unconfirmed"))
        raise_error(status, ask_code, str(detail.get("message", "")), cause=code)
