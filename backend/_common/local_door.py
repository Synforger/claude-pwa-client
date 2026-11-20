"""Whether a request came from a program on this machine, for the backend's doors that only such programs may use
(`tabs` and the commands a tab runs, a program that asks a tab). Called by the routes of those doors.

The sender's address alone does not tell it: `tailscale serve` hands the requests of the tailnet to the backend from
this machine's own address, so a phone opening the client's address looks local. It marks every request it hands on
with `X-Forwarded-Host` (and `X-Forwarded-For`), and removes any of these that the sender wrote, so a request from this
machine's own address that carries one came through it. A program on this machine that writes one itself only shuts
itself out. The doors for the other machine (`peers/`) check their own way and do not use this.

The doors the operator's screen uses (answering a ticket) are reached through `tailscale serve` on purpose: they take
the address alone (`from_this_machine_or_its_screen`), and the guard keeps the tabs off them.
"""
from __future__ import annotations

import logging

from fastapi import Request

from backend._common.errors import raise_error

logger = logging.getLogger(__name__)

#: The addresses of a request sent from this machine (`testclient` is the test client's).
LOCAL_CLIENTS = ("127.0.0.1", "::1", "localhost", "testclient")
#: The headers `tailscale serve` sets on every request it hands on to the backend.
PROXY_HEADERS = ("x-forwarded-host", "x-forwarded-for")
LOCAL_ONLY_MESSAGE = "この口は同じ機械の中からだけ使えます"


def from_this_machine(request: Request) -> bool:
    """Whether `request` was sent by a program on this machine, and not handed on by `tailscale serve`."""
    client_host = request.client.host if request.client else None
    return client_host in LOCAL_CLIENTS and not any(name in request.headers for name in PROXY_HEADERS)


def from_this_machine_or_its_screen(request: Request) -> bool:
    """Whether `request` was sent from this machine's own address: by a program on it, or by the operator's screen that
    `tailscale serve` hands on."""
    client_host = request.client.host if request.client else None
    return client_host in LOCAL_CLIENTS


def require_this_machine(request: Request, code: str) -> None:
    """Refuse `request` with `code` (403) unless it was sent by a program on this machine."""
    if from_this_machine(request):
        return
    client_host = request.client.host if request.client else None
    logger.warning("local door rejected: code=%s client=%s forwarded=%s", code, client_host,
                   request.headers.get("x-forwarded-for"))
    raise_error(403, code, LOCAL_ONLY_MESSAGE)
