"""Whether a request came from a program on this machine, for the backend's doors that only such programs may use
(`tabs` and the commands a tab runs, a program that asks a tab). Called by the routes of those doors.

The sender's address alone does not tell it: `tailscale serve` hands the requests of the tailnet to the backend from
this machine's own address, so a phone opening the client's address looks local. It marks every request it hands on
with `X-Forwarded-Host` (and `X-Forwarded-For`), and removes any of these that the sender wrote, so a request from this
machine's own address that carries one came through it. A program on this machine that writes one itself only shuts
itself out. The doors for the other machine (`peers/`) check their own way and do not use this.

The doors the operator's screen uses (answering a ticket) are reached through `tailscale serve` on purpose
(`from_this_machine_or_its_screen`), and the guard keeps the tabs off them. By the time a route reads the request,
uvicorn has put the address `tailscale serve` names in `X-Forwarded-For` in place of its own (it trusts that header
from this machine's own address only, and the backend listens on that address only), so a request from the
operator's phone shows the phone's tailnet address. A tailnet address is let in there; a public one (= a Funnel
request) is not.
"""
from __future__ import annotations

import ipaddress
import logging

from fastapi import Request

from backend._common.errors import raise_error

logger = logging.getLogger(__name__)

#: The addresses of a request sent from this machine (`testclient` is the test client's).
LOCAL_CLIENTS = ("127.0.0.1", "::1", "localhost", "testclient")
#: The headers `tailscale serve` sets on every request it hands on to the backend.
PROXY_HEADERS = ("x-forwarded-host", "x-forwarded-for")
LOCAL_ONLY_MESSAGE = "この口は同じ機械の中からだけ使えます"
#: The addresses Tailscale gives the devices of a tailnet (IPv4 CGNAT range and the Tailscale IPv6 prefix)
TAILNET_NETWORKS = (ipaddress.ip_network("100.64.0.0/10"), ipaddress.ip_network("fd7a:115c:a1e0::/48"))


def from_this_machine(request: Request) -> bool:
    """Whether `request` was sent by a program on this machine, and not handed on by `tailscale serve`."""
    client_host = request.client.host if request.client else None
    return client_host in LOCAL_CLIENTS and not any(name in request.headers for name in PROXY_HEADERS)


def from_this_machine_or_its_screen(request: Request) -> bool:
    """Whether `request` was sent by a program on this machine or by a device of the tailnet (= the operator's screen,
    which `tailscale serve` hands on)."""
    client_host = request.client.host if request.client else None
    return client_host in LOCAL_CLIENTS or is_tailnet_address(client_host)


def is_tailnet_address(host: str | None) -> bool:
    """Whether `host` is an address Tailscale gives a device of the tailnet."""
    try:
        address = ipaddress.ip_address(host or "")
    except ValueError:
        return False
    return any(address in network for network in TAILNET_NETWORKS)


def require_this_machine(request: Request, code: str) -> None:
    """Refuse `request` with `code` (403) unless it was sent by a program on this machine."""
    if from_this_machine(request):
        return
    client_host = request.client.host if request.client else None
    logger.warning("local door rejected: code=%s client=%s forwarded=%s", code, client_host,
                   request.headers.get("x-forwarded-for"))
    raise_error(403, code, LOCAL_ONLY_MESSAGE)
