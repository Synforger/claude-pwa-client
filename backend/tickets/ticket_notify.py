"""Tell the operator's devices that a ticket wants a look (`push.broadcast_push` with the ticket's id): when a tab put it in
front of the operator, when the operator's answer ended as not delivered or maybe not, and when no tab holds it any more. A
ticket kept inside a boundary is named by its id only (= its title is content). It never fails the change that caused it: a
failure is logged. Called by `ticket_service.py`, `answer_delivery.py` and `ticket_return.py`.
"""
from __future__ import annotations

import asyncio
import logging

from backend._common import paths
from backend.push.push import broadcast_push
from backend.tickets import ticket_file, ticket_index, ticket_places, ticket_view

logger = logging.getLogger(__name__)

_tasks: set[asyncio.Task] = set()


async def notify(ticket: str, reason: str, *, result: str | None = None) -> None:
    """Send the notification of `reason` (= one of `ticket_view.ATTENTION_*`) for the ticket. `result` is how the last delivery
    ended, for `ATTENTION_DELIVERY`."""
    try:
        row = ticket_index.get(ticket)
        if row is None:
            return
        title = None
        if row.place_key == ticket_places.outside_key():
            first = next(iter(await asyncio.to_thread(ticket_file.read, paths.TICKETS_DIR, ticket)), {})
            title = first.get("title") if isinstance(first.get("title"), str) else None
        heading, body = ticket_view.notice_of(ticket, title, reason, wants=row.wants, result=result)
        await broadcast_push(body, heading, None, ticket=ticket, tag=f"ticket-{ticket}")
        logger.info("ticket notified: id=%s reason=%s", ticket, reason)
    except Exception:
        logger.exception("ticket notified: id=%s reason=%s could not be sent", ticket, reason)


def schedule(ticket: str, reason: str, *, result: str | None = None) -> None:
    """Send the notification in the background (= the change that caused it does not wait for it, and does not fail with it)."""
    task = asyncio.create_task(notify(ticket, reason, result=result))
    _tasks.add(task)
    task.add_done_callback(_tasks.discard)
