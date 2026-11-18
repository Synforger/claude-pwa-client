"""The doors of the tickets, the requests that cross tabs (`docs/reference/tickets.md`): open one, add to it, ask the
operator through it, close it, hand it to another tab, read it, list them. The work is `backend/tickets/`; this file reads
the forms and checks the values. `tabs ticket` calls them. All of them answer calls from this machine only.
"""
from __future__ import annotations

from fastapi import APIRouter, Form, Request

from backend._common.errors import raise_error
from backend._common.state import sessions_meta
from backend.routes.agent_messages import LOCAL_CLIENTS
from backend.tickets import ticket_entry, ticket_id, ticket_pass, ticket_service

router = APIRouter()


def _from_this_machine(request: Request) -> None:
    client_host = request.client.host if request.client else None
    if client_host not in LOCAL_CLIENTS:
        raise_error(403, "ticket_local_only", "この口は同じ機械の中からだけ使えます")


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
    return await ticket_service.add(_known_tab(sender), _known_ticket(ticket), _not_empty(text, "本文"))


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
    if kind not in ticket_entry.ASK_KINDS:
        raise_error(400, "ticket_bad_kind", f"求める物は {', '.join(ticket_entry.ASK_KINDS)} のどれかで書いてください", kind=kind)
    return await ticket_service.ask(_known_tab(sender), _known_ticket(ticket), kind, _not_empty(text, "本文"),
                                    recommend if recommend and recommend.strip() else None)


@router.post("/tickets/{ticket}/close")
async def post_close(request: Request, ticket: str, sender: str = Form(..., alias="from"), text: str = Form("")) -> dict:
    """Close the ticket. form: from, text (optional, the last word)."""
    _from_this_machine(request)
    return await ticket_service.close(_known_tab(sender), _known_ticket(ticket), text)


@router.post("/tickets/{ticket}/pass")
async def post_pass(request: Request, ticket: str, sender: str = Form(..., alias="from"), to: str = Form("")) -> dict:
    """Hand the ticket to the tab `to` (= its id or name) and tell it in one line. form: from, to."""
    _from_this_machine(request)
    return await ticket_pass.pass_ticket(_known_tab(sender), _known_ticket(ticket), _not_empty(to, "宛先"))


@router.get("/tickets/{ticket}")
async def get_ticket(request: Request, ticket: str, reader: str) -> dict:
    """The ticket as the tab `reader` may read it, every line by time (`tabs ticket show`)."""
    _from_this_machine(request)
    return await ticket_service.show(_known_tab(reader), _known_ticket(ticket))


@router.get("/tickets")
async def get_tickets(request: Request) -> dict:
    """Every ticket with its title and state, for the operator's screen."""
    _from_this_machine(request)
    return await ticket_service.list_tickets()
