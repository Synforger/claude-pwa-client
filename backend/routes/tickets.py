"""The doors of the tickets, the requests that cross tabs (`docs/reference/tickets.md`): open one, add to it, ask the operator
through it, answer for the operator, close it, hand it to another tab, read it, list them. The work is `backend/tickets/`; this
file reads the forms and checks the values. `tabs ticket` calls them, and they answer calls from this machine only.

A ticket kept on the other machine (= the machine named in its id) is carried there: the same doors send `add`, `close`, `show`
and `pass` to that machine's backend (`ticket_relay.py`), and `ask` is refused (`ticket_ask_elsewhere`). The doors under
`/agent-messages/tickets` are the receiving end on the machine that keeps the ticket: they answer the configured other machine
only, and are the same ones the other machine's backend calls (`relay_home.py`).
"""
from __future__ import annotations

from fastapi import APIRouter, Body, Form, Request

from backend._common.local_door import LOCAL_ONLY_MESSAGE, from_this_machine_or_its_screen, require_this_machine
from backend._common.errors import raise_error
from backend._common.state import sessions_meta
from backend.routes.agent_messages import require_peer
from backend.tickets import (relay_home, ticket_answer, ticket_entry, ticket_id, ticket_operator, ticket_pass, ticket_relay,
                             ticket_service)

router = APIRouter()


def _from_this_machine(request: Request) -> None:
    require_this_machine(request, "ticket_local_only")


def _from_the_operators_screen(request: Request) -> None:
    """For the doors the operator's screen answers a ticket through: it reaches them through `tailscale serve`."""
    if not from_this_machine_or_its_screen(request):
        raise_error(403, "ticket_local_only", LOCAL_ONLY_MESSAGE)


def _known_tab(tab_id: str) -> str:
    if tab_id not in sessions_meta:
        raise_error(400, "ticket_unknown_sender", f"タブが見つかりません: {tab_id}", sender=tab_id)
    return tab_id


def _known_ticket(ticket: str) -> str:
    if not ticket_id.is_ticket_id(ticket):
        raise_error(404, "ticket_unknown", f"その id の票がありません: {ticket}", id=ticket)
    return ticket


def _not_empty(text: str, what: str) -> str:
    if not text.strip():
        raise_error(400, "ticket_empty", f"{what}が空です")
    return text


@router.post("/tickets")
async def post_ticket(
    request: Request,
    sender: str = Form(..., alias="from"),
    title: str = Form(""),
    text: str = Form(""),
    operator_said: bool = Form(False),
) -> dict:
    """Open a ticket. form: from (= the opening tab's id), title, text, operator_said (= true puts the operator's last words
    in that tab into the ticket, as the conversation's record has them).
    → `{ok, id, place_outside, operator_said}` and `operator_said_left_out` when the words could not go in."""
    _from_this_machine(request)
    return await ticket_service.open_ticket(_known_tab(sender), _not_empty(title, "題"), _not_empty(text, "本文"),
                                            operator_said=operator_said)


@router.post("/tickets/{ticket}/entries")
async def post_entry(request: Request, ticket: str, sender: str = Form(..., alias="from"), text: str = Form("")) -> dict:
    """Add what the tab `from` did to the ticket."""
    _from_this_machine(request)
    tab, known = _known_tab(sender), _known_ticket(ticket)
    if (home := ticket_relay.home_of(known)) is not None:
        return await ticket_relay.add(home, tab, known, _not_empty(text, "本文"))
    return await ticket_service.add(tab, known, _not_empty(text, "本文"))


@router.post("/tickets/{ticket}/asks")
async def post_ask(
    request: Request,
    ticket: str,
    sender: str = Form(..., alias="from"),
    kind: str = Form(""),
    text: str = Form(""),
    recommend: str | None = Form(None),
) -> dict:
    """Put the ticket in front of the operator. form: from, kind (= decide, mac or report), text, recommend (optional)."""
    _from_this_machine(request)
    if ticket_relay.home_of(_known_ticket(ticket)) is not None:
        raise_error(409, "ticket_ask_elsewhere",
                    "この票は別の機械にあります。 操作者に訊けるのは、 票がある機械のタブだけです。 票をその機械のタブへ渡すか、 この機械で票を開いて訊いてください",
                    id=ticket)
    if kind not in ticket_entry.ASK_KINDS:
        raise_error(400, "ticket_bad_kind", f"求める物は {', '.join(ticket_entry.ASK_KINDS)} のどれかで書いてください", kind=kind)
    return await ticket_service.ask(_known_tab(sender), _known_ticket(ticket), kind, _not_empty(text, "本文"),
                                    recommend if recommend and recommend.strip() else None)


@router.post("/tickets/{ticket}/answer")
async def post_answer(request: Request, ticket: str, body: dict = Body(...)) -> dict:
    """The operator's answer to the ticket that waits for it (= called by the operator's screen; the guard's `destinations`
    block it for the tabs). json: `asked_at` (= the `at` of the `asked` line the screen was showing) and `text`, or
    `recommend: true` for the recommendation of that line (= `text` is not read then).
    → `{ok, id, queued}`: the answer is written and waits for the tab that holds the ticket."""
    _from_the_operators_screen(request)
    asked_at, text, recommend = body.get("asked_at"), body.get("text", ""), body.get("recommend", False) is True
    if not isinstance(asked_at, str) or not asked_at.strip() or not isinstance(text, str):
        raise_error(400, "ticket_bad_answer", "答えは asked_at (= 見ていた問いの時刻) と、 text か recommend: true で送ってください")
    return await ticket_answer.answer(_known_ticket(ticket), asked_at, text if recommend else _not_empty(text, "答え"),
                                      recommend)


def _kept_here(ticket: str) -> str:
    """The operator's doors work on a ticket kept on this machine (= the other machine's ticket is read on its own screen)."""
    if (home := ticket_relay.home_of(_known_ticket(ticket))) is not None:
        raise_error(409, "ticket_elsewhere", f"この票は {home.name} の機械にあります。 その機械の画面で読んで答えてください",
                    id=ticket, peer=home.name)
    return ticket


@router.get("/tickets/{ticket}/answer")
async def get_ticket_for_operator(request: Request, ticket: str) -> dict:
    """The ticket as the operator reads it, every line and nothing judged (= called by the operator's screen; the guard's
    `destinations` block this door for the tabs, as the one that answers)."""
    _from_the_operators_screen(request)
    return await ticket_operator.read(_kept_here(ticket))


@router.post("/tickets/{ticket}/answer/holder")
async def post_holder(request: Request, ticket: str, body: dict = Body(...)) -> dict:
    """The operator hands a ticket no tab holds to a tab. json: `to` (= the tab's id). → `{ok, id, to, kept?}`."""
    _from_the_operators_screen(request)
    to = body.get("to")
    if not isinstance(to, str) or not to.strip():
        raise_error(400, "ticket_empty", "渡す先のタブが空です")
    return await ticket_operator.hand_to(_kept_here(ticket), to.strip())


@router.post("/tickets/{ticket}/answer/seen")
async def post_seen(request: Request, ticket: str) -> dict:
    """The operator looked at an answer that did not arrive (or may not have): it stops wanting a look. → `{ok, id, written}`."""
    _from_the_operators_screen(request)
    return await ticket_operator.seen(_kept_here(ticket))


@router.post("/tickets/{ticket}/close")
async def post_close(request: Request, ticket: str, sender: str = Form(..., alias="from"), text: str = Form("")) -> dict:
    """Close the ticket. form: from, text (optional, the last word)."""
    _from_this_machine(request)
    tab, known = _known_tab(sender), _known_ticket(ticket)
    if (home := ticket_relay.home_of(known)) is not None:
        return await ticket_relay.close(home, tab, known, text)
    return await ticket_service.close(tab, known, text)


@router.post("/tickets/{ticket}/pass")
async def post_pass(request: Request, ticket: str, sender: str = Form(..., alias="from"), to: str = Form("")) -> dict:
    """Hand the ticket to the tab `to` (= its id or name; `<machine>:<tab>` for a tab of the other machine) and tell it in one
    line. form: from, to."""
    _from_this_machine(request)
    tab, known = _known_tab(sender), _known_ticket(ticket)
    if (home := ticket_relay.home_of(known)) is not None:
        return await ticket_relay.pass_ticket(home, tab, known, _not_empty(to, "宛先"))
    return await ticket_pass.pass_ticket(tab, known, _not_empty(to, "宛先"))


@router.get("/tickets/{ticket}")
async def get_ticket(request: Request, ticket: str, reader: str) -> dict:
    """The ticket as the tab `reader` may read it, every line by time (`tabs ticket show`)."""
    _from_this_machine(request)
    tab, known = _known_tab(reader), _known_ticket(ticket)
    if (home := ticket_relay.home_of(known)) is not None:
        return await ticket_relay.show(home, tab, known)
    return await ticket_service.show(tab, known)


@router.get("/tickets")
async def get_tickets(request: Request) -> dict:
    """Every ticket with its title and state, for the operator's screen (= the `tickets` channel of the unified stream carries
    the same list)."""
    _from_this_machine(request)
    return await ticket_service.list_tickets()


# --- the receiving end: the other machine's backend calls these on the machine that keeps the ticket ---


def _relay_text(body: dict, name: str, *, may_be_empty: bool = False) -> str:
    value = body.get(name)
    if not isinstance(value, str) or not (value.strip() or may_be_empty):
        raise_error(400, "ticket_bad_relay", "別の機械から届いた票の操作の形が正しくありません", field=name)
    return value


@router.post("/agent-messages/tickets/{ticket}/entries")
async def post_relayed_entry(request: Request, ticket: str, body: dict = Body(...)) -> dict:
    """The other machine's tab adds a line to a ticket kept here (= json: from_session, from_title, text)."""
    peer_name, _peer = require_peer(request)
    return await relay_home.add(peer_name, _known_ticket(ticket), _relay_text(body, "from_session"),
                                _relay_text(body, "from_title"), _relay_text(body, "text"))


@router.post("/agent-messages/tickets/{ticket}/close")
async def post_relayed_close(request: Request, ticket: str, body: dict = Body(...)) -> dict:
    """The other machine's tab closes a ticket kept here (= json: from_session, from_title, text, which may be empty)."""
    peer_name, _peer = require_peer(request)
    return await relay_home.close(peer_name, _known_ticket(ticket), _relay_text(body, "from_session"),
                                  _relay_text(body, "from_title"), _relay_text(body, "text", may_be_empty=True))


@router.post("/agent-messages/tickets/{ticket}/pass")
async def post_relayed_pass(request: Request, ticket: str, body: dict = Body(...)) -> dict:
    """The other machine's tab hands a ticket kept here to a tab (= json: from_session, from_title, to_machine, to)."""
    peer_name, _peer = require_peer(request)
    return await ticket_pass.pass_from_peer(peer_name, _relay_text(body, "from_session"), _relay_text(body, "from_title"),
                                            _known_ticket(ticket), _relay_text(body, "to_machine"), _relay_text(body, "to"))


@router.post("/agent-messages/tickets/{ticket}/notify")
async def post_relayed_notify(request: Request, ticket: str, body: dict = Body(...)) -> dict:
    """The other machine (which keeps the ticket) asks this one to tell a tab here the ticket was handed to it (= json: to,
    from_machine, from_session, from_title)."""
    peer_name, peer = require_peer(request)
    return await relay_home.notify(peer_name, peer, _known_ticket(ticket), _relay_text(body, "to"),
                                   _relay_text(body, "from_machine"), _relay_text(body, "from_session"),
                                   _relay_text(body, "from_title"))


@router.get("/agent-messages/tickets/{ticket}")
async def get_relayed_ticket(request: Request, ticket: str, reader: str) -> dict:
    """The ticket kept here as the other machine's tab `reader` may read it."""
    peer_name, _peer = require_peer(request)
    return await relay_home.show(peer_name, _known_ticket(ticket), reader)


@router.get("/agent-messages/tickets")
async def get_relayed_tickets(request: Request) -> dict:
    """The tickets kept here outside every boundary, for the other machine's screen (= no title)."""
    peer_name, _peer = require_peer(request)
    return await relay_home.list_tickets(peer_name)
