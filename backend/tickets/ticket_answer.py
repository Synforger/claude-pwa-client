"""The operator's answer to a ticket that waits for it: check the answer is to the `asked` line the screen was showing, write
it into the ticket (the `answered` line and the row, together under the ticket's lock), queue it for the tab that holds the
ticket and start delivering it (`answer_delivery.py`). Nothing of the answer is judged by the guard (= it is the operator's
own words); `answer_delivery.py` only makes sure the holder has read the ticket's boundary. Called by `routes/tickets.py`.
"""
from __future__ import annotations

import asyncio

from backend._common.errors import raise_error
from backend.tickets import answer_delivery, answer_queue, ticket_entry, ticket_file, ticket_places, ticket_service
from backend.tickets.answer_queue import AnswerKey
from backend.tickets.ticket_index import OPEN, WAITING_OPERATOR, IndexRow


def _last_asked(entries: list[dict]) -> dict | None:
    return next((entry for entry in reversed(entries) if entry.get("kind") == ticket_entry.ASKED), None)


def _asked_line(row: IndexRow, entries: list[dict], ticket: str, asked_at: str, recommend: bool) -> dict:
    """The `asked` line the answer is to, once the ticket is known to take it. Refuses, in this order: a ticket that does not
    wait for the operator, an answer to a line that is not the last `asked` one (= the screen was showing an old one), a
    ticket no tab holds, and a recommendation that is not there."""
    if row.status != WAITING_OPERATOR:
        raise_error(409, "ticket_not_waiting", f"その票は操作者の返事を待っていません: {ticket}", id=ticket)
    asked = _last_asked(entries)
    if asked is None or asked.get("at") != asked_at:
        raise_error(409, "ticket_ask_changed", "画面が見ていた問いは、 もう替わっています。 見直して答えてください", id=ticket)
    if not row.holder:
        raise_error(409, "ticket_no_holder", "この票を持つタブがありません。 渡す先を選んでください", id=ticket)
    if recommend and not asked.get("recommend"):
        raise_error(409, "ticket_no_recommend", "その問いには推奨がありません。 文で答えてください", id=ticket)
    return asked


async def answer(ticket: str, asked_at: str, text: str, recommend: bool) -> dict:
    """Take the operator's answer to the `asked` line `asked_at` of the ticket: the words `text`, or with `recommend` the
    recommendation that line carried. → `{"ok", "id", "queued"}`; the answer reaches the holder in the background."""
    row = ticket_service.row_of(ticket)
    folder = await ticket_places.folder_for(row.place_key)
    entries = await asyncio.to_thread(ticket_file.read, folder, ticket)
    asked = _asked_line(row, entries, ticket, asked_at, recommend)
    words = str(asked["recommend"]) if recommend else text
    key = AnswerKey(ticket, asked_at)
    entry = ticket_entry.make_entry(ticket_entry.ANSWERED, ticket_entry.CLIENT_WRITER, words, at=ticket_service.now(),
                                    asked_at=asked_at, recommended=recommend)

    def still_the_same(current: IndexRow) -> None:
        # the screen's answer is checked again under the lock: another change may have landed since the file was read
        _asked_line(current, ticket_file.read(folder, ticket), ticket, asked_at, recommend)

    await asyncio.to_thread(ticket_service.write_entry, ticket, folder, entry, {"status": OPEN, "wants": None},
                            check=still_the_same, after=lambda: answer_queue.add(key))
    answer_delivery.start_delivery(key)
    return {"ok": True, "id": ticket, "queued": True}
