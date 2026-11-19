"""What the operator's screen needs to know of a ticket, worked out from its lines and its row: which answers are still on
their way, how the last delivery ended, which tickets want a look (`attention`) and how many tickets the other machine has
waiting for the operator. Pure: no file, no tab, no clock. Called by `ticket_service.py`, `ticket_operator.py` and
`ticket_peer_count.py`.
"""
from __future__ import annotations

from backend.tickets import ticket_entry
from backend.tickets.ticket_index import WAITING_OPERATOR, CLOSED

#: The reasons a ticket wants a look (= `attention`): it waits for the operator's answer, the operator's answer did not
#: arrive (or may not have), and no tab holds it
ATTENTION_WAITING = "waiting"
ATTENTION_DELIVERY = "delivery"
ATTENTION_NO_HOLDER = "no_holder"
#: The `delivered` results that leave the operator something to look at
_UNSETTLED_RESULTS = ("refused", "unconfirmed")


def answer_pending(entries: list[dict]) -> list[str]:
    """The `asked_at` of every answer the operator gave that has no `delivered` line yet (= still on its way to the holder),
    in the order they were given."""
    delivered = {entry.get("asked_at") for entry in entries if entry.get("kind") == ticket_entry.DELIVERED}
    return [entry["asked_at"] for entry in entries
            if entry.get("kind") == ticket_entry.ANSWERED and isinstance(entry.get("asked_at"), str)
            and entry["asked_at"] not in delivered]


def last_delivery(entries: list[dict]) -> dict | None:
    """How the last delivery ended: `{"result", "followed"}`, `followed` being whether any line comes after it (= the
    operator's `seen`, or the tab's own work). None when nothing was delivered."""
    for index in range(len(entries) - 1, -1, -1):
        if entries[index].get("kind") == ticket_entry.DELIVERED:
            return {"result": str(entries[index].get("result", "")), "followed": index < len(entries) - 1}
    return None


def last_at(entries: list[dict]) -> str:
    """The time of the last line ("" when there is none)."""
    return str(entries[-1].get("at", "")) if entries else ""


def attention(status: str, holder: str, delivery: dict | None) -> str | None:
    """Why the ticket is in the screen's first group (= the first reason that fits), or None. A ticket waits for a look when
    it waits for the operator's answer, when the last answer did not arrive (or may not have) and nothing came after it, or
    when no tab holds it and it is not closed."""
    if status == WAITING_OPERATOR:
        return ATTENTION_WAITING
    if delivery is not None and delivery["result"] in _UNSETTLED_RESULTS and not delivery["followed"]:
        return ATTENTION_DELIVERY
    if status != CLOSED and not holder:
        return ATTENTION_NO_HOLDER
    return None


#: What a notification says of a ticket that waits for the operator, by what it asks (`wants`), and of one whose answer did
#: not arrive, by how the delivery ended
_BODY_BY_WANTS = {"decide": "Waiting for your decision", "mac": "Needs you at the Mac", "report": "A report to read"}
_BODY_BY_RESULT = {"refused": "Your answer was not delivered", "unconfirmed": "Check that your answer arrived"}
_BODY_NO_HOLDER = "No tab holds this ticket"
_BODY_FALLBACK = "Waiting for you"
#: The mark in front of a notification's title
PIN = "📌"


def notice_of(ticket: str, title: str | None, reason: str, *, wants: str | None = None, result: str | None = None) -> tuple[str, str]:
    """The title and the words of the notification that a ticket wants a look. `title` is None for a ticket kept inside a
    boundary: its title is content, so only its id is shown. `wants` says what it asks (`reason` = `ATTENTION_WAITING`),
    `result` how the last delivery ended (`ATTENTION_DELIVERY`)."""
    heading = f"{PIN} {title}" if title else f"{PIN} Ticket {ticket}"
    if reason == ATTENTION_WAITING:
        return heading, _BODY_BY_WANTS.get(wants or "", _BODY_FALLBACK)
    if reason == ATTENTION_DELIVERY:
        return heading, _BODY_BY_RESULT.get(result or "", _BODY_FALLBACK)
    return heading, _BODY_NO_HOLDER


def waiting_count(listing: object) -> int | None:
    """How many tickets of the other machine's list wait for the operator. None when `listing` is not a list of tickets
    (= the machine did not give one, which the screen shows as unreadable, not as no ticket)."""
    tickets = listing.get("tickets") if isinstance(listing, dict) else None
    if not isinstance(tickets, list):
        return None
    return sum(1 for ticket in tickets if isinstance(ticket, dict) and ticket.get("status") == WAITING_OPERATOR)
