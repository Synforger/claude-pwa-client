"""Deliver the operator's answers to the tabs that hold the tickets they answer. An answer waits in the queue
(`answer_queue.py`) until it is typed into the holder's claude, which is tried by three things: the answer being queued
(`start_delivery`), the holder's turn ending (`on_stop`, from the `Stop` hook) and a patrol every `PATROL_SEC`
(`patrol_loop`, started from `backend/main.py`). All three do the same thing (`deliver`): under the lock of that one answer,
look at the facts, type the answer, see what came of it and only then take it out of the queue. What to do for each case is
`answer_judgement.py`; the words are read from the ticket's own `answered` line. See `docs/reference/tickets.md`.
"""
from __future__ import annotations

import asyncio
import logging
import time

from fastapi import HTTPException

from backend._common.state import sessions_meta
from backend.jsonl.jsonl_predicates import ticket_answer_envelope
from backend.rollover import rollover
from backend.routes.agent_messages import deliver_or_keep, hand_over_work, tab_reachable
from backend.routes.overview import is_busy
from backend.terminal.runner import jsonl_path_for_session
from backend.tickets import answer_judgement, answer_queue, ticket_checks, ticket_entry, ticket_file, ticket_index
from backend.tickets import ticket_notify, ticket_places, ticket_return, ticket_service, ticket_view
from backend.tickets.answer_judgement import AnswerFacts
from backend.tickets.answer_queue import AnswerKey
from backend.tickets.ticket_index import CLOSED, IndexRow

logger = logging.getLogger(__name__)

#: How often the queue is looked over
PATROL_SEC = 5.0
#: How long after the backend starts nothing is looked over: until the screen's live view fills in, `is_busy` can be false
#: for a tab that is working
STARTUP_QUIET_SEC = 30.0

# What is written in a `delivered` line (and in the log) as the result
TYPED = "typed"
KEPT = "kept"
_WAITING = "waiting"

_locks: dict[AnswerKey, asyncio.Lock] = {}
#: The wait before the next try of an answer that was refused before anything was typed, and when that try is due
#: (`time.monotonic`). Memory only: after a restart every answer is tried at the first look.
_retry_after: dict[AnswerKey, tuple[float, float]] = {}
#: The last thing logged for an answer that is only waiting, so that a look every few seconds logs a change once
_last_waiting: dict[AnswerKey, str] = {}
_quiet_until = 0.0
_tasks: set[asyncio.Task] = set()


def _lock_for(key: AnswerKey) -> asyncio.Lock:
    return _locks.setdefault(key, asyncio.Lock())


def _facts_of(row: IndexRow | None) -> AnswerFacts:
    """What is known of the answer now: the ticket's row, and the holder's claude (= working, asked to close)."""
    if row is None:
        return AnswerFacts(False, False, "", False, False, False, False, False)
    holder, here = row.holder, row.holder in sessions_meta
    busy, close_asked, reachable = False, False, False
    if here:
        record = jsonl_path_for_session(holder)
        busy = is_busy(holder)
        close_asked = record is not None and rollover.asked(record)
        reachable = tab_reachable(holder)
    return AnswerFacts(has_row=True, closed=row.status == CLOSED, holder=holder, holder_is_remote=":" in holder,
                       holder_here=here, reachable=reachable, busy=busy, close_asked=close_asked)


def _log(level: int, key: AnswerKey, holder: str, result: str) -> None:
    logger.log(level, "ticket answer: id=%s asked_at=%s holder=%s result=%s", key.ticket, key.asked_at, holder, result)


def _log_waiting(key: AnswerKey, holder: str, result: str) -> None:
    """Log an answer that stays in the queue, once for each change of what it waits for."""
    if _last_waiting.get(key) != result:
        _last_waiting[key] = result
        _log(logging.INFO, key, holder, result)


def _finish(key: AnswerKey) -> None:
    """The answer is out of the queue for good: forget what was kept of it."""
    answer_queue.remove(key)
    _retry_after.pop(key, None)
    _last_waiting.pop(key, None)
    _locks.pop(key, None)


async def _record(key: AnswerKey, row: IndexRow, result: str) -> None:
    """Write the `delivered` line (= what became of the answer). A line that cannot be written is logged: the answer was
    typed already, and a restart that finds no line tries it again, which is the lesser harm."""
    entry = ticket_entry.make_entry(ticket_entry.DELIVERED, ticket_entry.CLIENT_WRITER, "", at=ticket_service.now(),
                                    asked_at=key.asked_at, result=result, to=row.holder)
    try:
        folder = await ticket_places.folder_for(row.place_key)
        await asyncio.to_thread(ticket_service.record, key.ticket, folder, entry)
    except Exception:
        logger.exception("ticket answer: the delivered line of id=%s asked_at=%s could not be written", key.ticket, key.asked_at)
        return
    if result in (answer_judgement.REFUSED, answer_judgement.UNCONFIRMED):
        # the answer did not arrive, or may not have: the operator's devices are told, and the ticket wants a look
        ticket_notify.schedule(key.ticket, ticket_view.ATTENTION_DELIVERY, result=result)


def _answered_text(entries: list[dict], asked_at: str) -> tuple[str | None, bool]:
    """The words of the `answered` line for `asked_at`, and whether a `delivered` line for it is there already."""
    text = next((entry.get("text", "") for entry in entries
                 if entry.get("kind") == ticket_entry.ANSWERED and entry.get("asked_at") == asked_at), None)
    delivered = any(entry.get("kind") == ticket_entry.DELIVERED and entry.get("asked_at") == asked_at for entry in entries)
    return text, delivered


def _back_off(key: AnswerKey) -> float:
    """Take the next wait of this answer (= grown from the last one) and set when it is next tried."""
    previous = _retry_after.get(key)
    wait = answer_judgement.retry_after_sec(previous[1] if previous else None)
    _retry_after[key] = (time.monotonic() + wait, wait)
    return wait


async def _type_answer(key: AnswerKey, row: IndexRow) -> None:
    """Type the answer into the holder's claude and settle it by what came of that."""
    folder = await ticket_places.folder_for(row.place_key)
    await ticket_checks.check_covers(row.holder, folder)
    text, delivered = _answered_text(await asyncio.to_thread(ticket_file.read, folder, key.ticket), key.asked_at)
    if text is None or delivered:
        logger.warning("ticket answer: id=%s asked_at=%s has %s; it is taken out of the queue", key.ticket, key.asked_at,
                       "been delivered already" if delivered else "no answered line")
        _finish(key)
        return
    result = await deliver_or_keep(row.holder, ticket_answer_envelope(key.ticket, text, closed=row.status == CLOSED))
    outcome = KEPT if result.get("kept") else (TYPED if result.get("ok") else answer_judgement.UNCONFIRMED)
    await _record(key, row, outcome)
    # The answer is work for the holder: a child that reported (= it waited for the operator) holds work again, the same
    # as when its parent hands it more.
    parent = sessions_meta[row.holder].parent_id if row.holder in sessions_meta else None
    if parent:
        await hand_over_work(parent, row.holder)
    _finish(key)
    _log(logging.WARNING if outcome == answer_judgement.UNCONFIRMED else logging.INFO, key, row.holder, outcome)


async def _settle_failure(key: AnswerKey, row: IndexRow, error: HTTPException) -> None:
    """A delivery that did not complete: by the code, try it again after a wait, let it go as maybe arrived, or let it go
    because the tab may not have it."""
    code = error.detail.get("code", "") if isinstance(error.detail, dict) else ""
    what = answer_judgement.after_failure(code)
    if what == answer_judgement.RETRY:
        wait = _back_off(key)
        _log(logging.INFO, key, row.holder, f"retry in {wait:.0f}s ({code or error.status_code})")
        return
    await _record(key, row, what)
    _finish(key)
    _log(logging.WARNING, key, row.holder, f"{what} ({code})")


async def _deliver_locked(key: AnswerKey) -> None:
    """One look at one answer, under its lock."""
    row = ticket_index.get(key.ticket)
    step = answer_judgement.next_step(_facts_of(row))
    if step == answer_judgement.RETURN_HOLDER:
        try:
            await ticket_return.return_if_gone(key.ticket)
        except HTTPException as error:
            logger.info("ticket answer: id=%s could not be given back to its first tab now: %s", key.ticket, error.detail)
        row = ticket_index.get(key.ticket)
        step = answer_judgement.next_step(_facts_of(row))
    holder = row.holder if row else ""
    if step == answer_judgement.DROP_NO_TICKET:
        logger.warning("ticket answer: id=%s asked_at=%s has no row in the index; it is taken out of the queue",
                       key.ticket, key.asked_at)
        _finish(key)
    elif step == answer_judgement.NO_RECEIVER and row is not None:
        await _record(key, row, answer_judgement.REFUSED)
        _finish(key)
        _log(logging.WARNING, key, holder, "refused (the ticket is closed and its holder is gone)")
    elif step in (answer_judgement.WAIT_NO_HOLDER, answer_judgement.RETURN_HOLDER):
        _log_waiting(key, holder, f"{_WAITING} (no tab holds the ticket)")
    elif step == answer_judgement.WAIT_BUSY:
        _log_waiting(key, holder, f"{_WAITING} (the tab is working)")
    elif step == answer_judgement.RETRY_UNREACHABLE and row is not None:
        wait = _back_off(key)
        _log(logging.INFO, key, holder, f"retry in {wait:.0f}s (the tab cannot be reached)")
    elif row is not None:
        try:
            await _type_answer(key, row)
        except HTTPException as error:
            await _settle_failure(key, row, error)


async def deliver(key: AnswerKey, *, from_patrol: bool = False) -> None:
    """Look at one answer and deliver it when it can be. The patrol leaves an answer whose wait after a refusal is not over;
    the other two triggers (= the answer queued, the tab's turn ended) are news and look at once. An answer that
    fails for a reason nobody foresaw stays in the queue and is tried again after a wait."""
    async with _lock_for(key):
        if not answer_queue.contains(key):
            return
        due = _retry_after.get(key)
        if from_patrol and due is not None and time.monotonic() < due[0]:
            return
        try:
            await _deliver_locked(key)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("ticket answer: id=%s asked_at=%s failed unexpectedly", key.ticket, key.asked_at)
            _back_off(key)


def start_delivery(key: AnswerKey) -> None:
    """Deliver the answer that was just queued, in the background (= the door does not wait for the tab). Within the
    first `STARTUP_QUIET_SEC` of the backend it is left to the patrol, which starts after that."""
    if time.monotonic() < _quiet_until:
        return
    task = asyncio.create_task(deliver(key))
    _tasks.add(task)
    task.add_done_callback(_tasks.discard)


async def on_stop(tab_id: str) -> None:
    """The tab's turn ended: deliver the answers waiting for it. Called from the `Stop` hook as a task, so the hook is not
    kept waiting."""
    try:
        for key in answer_queue.keys():
            row = ticket_index.get(key.ticket)
            if row is not None and row.holder == tab_id:
                await deliver(key)
    except asyncio.CancelledError:
        raise
    except Exception:
        logger.exception("ticket answer: delivering on the stop of session=%s failed", tab_id)


async def restore_queue() -> bool:
    """Queue again every answer the ticket files show was given and never delivered (= what the queue lost between the file
    being written and the queue: the answer is in the file first). → True when every ticket was read."""
    complete = True
    for ticket, row in list(ticket_index.rows().items()):
        try:
            folder = await ticket_places.folder_for(row.place_key)
        except HTTPException as error:
            logger.warning("ticket answer: the answers of id=%s were not looked for: %s", ticket, error.detail)
            complete = False
            continue
        entries = await asyncio.to_thread(ticket_file.read, folder, ticket)
        delivered = {entry.get("asked_at") for entry in entries if entry.get("kind") == ticket_entry.DELIVERED}
        for entry in entries:
            asked_at = entry.get("asked_at")
            if entry.get("kind") == ticket_entry.ANSWERED and isinstance(asked_at, str) and asked_at not in delivered:
                if answer_queue.add(AnswerKey(ticket, asked_at)):
                    logger.info("ticket answer: id=%s asked_at=%s was queued again", ticket, asked_at)
    return complete


async def patrol_once() -> None:
    """Look at every answer in the queue once, oldest first."""
    for key in answer_queue.keys():
        await deliver(key, from_patrol=True)


async def patrol_loop(interval_sec: float = PATROL_SEC) -> None:
    """Look over the queue every `interval_sec`, the first time `STARTUP_QUIET_SEC` after this starts."""
    global _quiet_until
    _quiet_until = time.monotonic() + STARTUP_QUIET_SEC
    logger.info("ticket answer patrol started (interval=%ds, quiet=%ds)", interval_sec, STARTUP_QUIET_SEC)
    restored = False
    try:
        await asyncio.sleep(STARTUP_QUIET_SEC)
        while True:
            try:
                if not restored:
                    restored = await restore_queue()
                await patrol_once()
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("ticket answer patrol iteration failed")
            await asyncio.sleep(interval_sec)
    except asyncio.CancelledError:
        logger.info("ticket answer patrol cancelled")
        raise
