"""What the operator's screen and a tab's own list need to know of a ticket, worked out from its lines and its row: which
answers are still on their way, how the last delivery ended, which tickets want a look (`attention`), how many tickets the
other machine has waiting for the operator, the marks that say a ticket needs another look (`marks`) and, for the tab that
holds it, where it came from, what its last line asks and whether the tab itself has written since a time. Pure: no file, no
tab, no clock (= the caller passes the day and the time). Called by `ticket_service.py`, `ticket_operator.py`,
`ticket_held.py` and `ticket_peer_count.py`.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

from backend.tickets import ticket_entry
from backend.tickets.ticket_index import CLOSED, OPEN, ORIGIN_OPERATOR, WAITING, WAITING_OPERATOR

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
TICKET_MARK = "🎫"


def notice_of(ticket: str, title: str | None, reason: str, *, wants: str | None = None, result: str | None = None) -> tuple[str, str]:
    """The title and the words of the notification that a ticket wants a look. `title` is None for a ticket kept inside a
    boundary: its title is content, so only its id is shown. `wants` says what it asks (`reason` = `ATTENTION_WAITING`),
    `result` how the last delivery ended (`ATTENTION_DELIVERY`)."""
    heading = f"{TICKET_MARK} {title}" if title else f"{TICKET_MARK} Ticket {ticket}"
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


#: The marks of a ticket that needs another look (= `marks`, in the order they are given): its due day is past, its due day is
#: within `DUE_SOON_DAYS` days, it has waited more than `WAITING_STALE_DAYS` days, it has been open and still for `IDLE_DAYS`
OVERDUE = "overdue"
DUE_SOON = "due_soon"
WAITING_STALE = "waiting_stale"
IDLE = "idle"
DUE_SOON_DAYS = 2
WAITING_STALE_DAYS = 5
IDLE_DAYS = 14
#: Where a ticket came from, for the tab that holds it: the operator's words, another tab's request, its own
SOURCE_OPERATOR = "operator"
SOURCE_TAB = "tab"
SOURCE_SELF = "self"


def parse_time(text: object) -> datetime | None:
    """A line's time (ISO, `Z` or an offset; no offset is UTC) as a moment, or None when `text` is not one. Times are
    compared as moments, never as text: the record's `Z` and a line's `+00:00` do not sort alike."""
    if not isinstance(text, str):
        return None
    try:
        moment = datetime.fromisoformat(text)
    except ValueError:
        return None
    return moment if moment.tzinfo else moment.replace(tzinfo=timezone.utc)


def is_tab_line(entry: dict) -> bool:
    """Whether a tab wrote the line (= the lines the client writes, `answered`, `delivered`, `returned`, `seen` and the
    operator's hand-over, have no tab)."""
    return bool(entry.get("tab"))


def last_tab_time(entries: list[dict]) -> str:
    """The time of the last line a tab wrote ("" when there is none): what the age marks count from, since a line the client
    writes is no sign that anyone worked on the ticket."""
    return next((str(entry.get("at", "")) for entry in reversed(entries) if is_tab_line(entry)), "")


def marks(status: str, due: str | None, last_tab_at: str, today: date, now: datetime) -> list[str]:
    """Every mark that fits, in the order `overdue`, `due_soon`, `waiting_stale`, `idle`. `today` is the day by the clock
    on the wall (= due days are days of the place the operator is in) and `now` a moment in UTC. A ticket waiting for the
    operator has only the two due marks and a closed one has none. "More than 5 days" is 5 days or more, so the mark comes
    on the fifth day. `last_tab_at` is the time of the last line a tab wrote (`last_tab_time`); an age mark needs one."""
    if status == CLOSED:
        return []
    found = []
    try:
        day = date.fromisoformat(due) if due else None
    except ValueError:
        day = None
    if day is not None and day < today:
        found.append(OVERDUE)
    elif day is not None and day <= today + timedelta(days=DUE_SOON_DAYS):
        found.append(DUE_SOON)
    last = parse_time(last_tab_at)
    if last is not None and status == WAITING and now - last >= timedelta(days=WAITING_STALE_DAYS):
        found.append(WAITING_STALE)
    if last is not None and status == OPEN and now - last >= timedelta(days=IDLE_DAYS):
        found.append(IDLE)
    return found


def source_of(origin: str, opener: str, holder: str) -> str:
    """Where a ticket came from, as the tab that holds it sees it: `operator` when the operator's words went in when it opened,
    `tab` when another tab than the holder opened it (= it was handed on, or is the other machine's), else `self`."""
    if origin == ORIGIN_OPERATOR:
        return SOURCE_OPERATOR
    return SOURCE_TAB if opener != holder else SOURCE_SELF


def latest_tab_line(entries: list[dict]) -> dict | None:
    """The last line a tab wrote that has any text (= not the hand-over line, which says nothing, and not the operator's words,
    which the tab only quoted), or None. It is the line itself, not a copy, so the caller can match it with what the guard let
    the reader see of it."""
    return next((entry for entry in reversed(entries) if is_tab_line(entry) and entry.get("kind") != ticket_entry.OPERATOR
                 and str(entry.get("text", "")).strip()), None)


def first_line(text: object) -> str:
    """The first line of `text` ("" when it has none or is not text)."""
    lines = text.strip().splitlines() if isinstance(text, str) else []
    return lines[0].strip() if lines else ""


def written_since(entries: list[dict], tab: str, since: str) -> bool | None:
    """Whether the tab `tab` wrote a line at or after `since` (= the tab itself: a line the client writes, or another tab, does
    not count). None when `since` is not a time."""
    start = parse_time(since)
    if start is None:
        return None
    return any(entry.get("tab") == tab and (at := parse_time(entry.get("at"))) is not None and at >= start for entry in entries)


def held_item(ticket: str, *, status: str, origin: str, opener: str, holder: str, due: str | None, entries: list[dict],
              title: str | None, next_step: str, writable: bool, since: str | None, today: date, now: datetime) -> dict:
    """One ticket in the list of what the tab `holder` holds (`tabs ticket mine`). `entries` are the ticket's lines (= only
    their tab and time are read); `title` and `next_step` are what the tab may read of the first line and of the last line a tab
    wrote. `written_since` is None when no `since` was given."""
    last = last_tab_time(entries)
    return {"id": ticket, "title": title, "status": status, "source": source_of(origin, opener, holder), "due": due,
            "marks": marks(status, due, last, today, now), "next": next_step, "last_at": last,
            "written_since": written_since(entries, holder, since) if since else None, "writable": writable}
