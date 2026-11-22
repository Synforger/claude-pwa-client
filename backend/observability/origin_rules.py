"""The table of where this client's own requests come from. It is observed and never enforced: the caller logs the
rows a request is outside of, and every request goes on.

Called by `request_origin.py`. This file only computes: the labels of a request and what `tailscale serve` reported
come in, and the names of the rows come out.

- A: the Host is one of the listener's own names
- B: a request that changes state has one of the listener's own origins, or none and no word of another site
- C: a WebSocket has one of the listener's own origins, or none
- D: a GET that changes state is held to B, and is no navigation

A request with neither an Origin nor fetch metadata is a program or the app's native part; the table does not tell who
that is, and is no authentication.
"""
from __future__ import annotations

from typing import NamedTuple

from backend.page_url.page_url import DEFAULT_PORTS, listeners_of

NONE_LABEL = "(none)"
WEBSOCKET_METHOD = "WS"
READING_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})
OWN_SITES = frozenset({NONE_LABEL, "same-origin", "none"})
NAVIGATE = "navigate"
# The GETs that change state. A page of a document keeps a bounded cache and is opened by navigating, so it is none.
STATE_CHANGING_GETS = frozenset({"/stream/unified"})
LOOPBACK_NAMES = ("127.0.0.1", "localhost", "[::1]")
# The one row of a request that cannot be told apart, because this machine's names have not been read.
UNREAD = "unread"


class RequestFacts(NamedTuple):
    """What the table reads of a request; every field is a label."""

    method: str
    template: str
    host: str
    origin: str
    fetch_site: str
    fetch_mode: str


class KnownNames(NamedTuple):
    """One listener's own Host values and origins."""

    hosts: frozenset[str]
    origins: frozenset[str]
    is_read: bool


def known_names(port: int, serve_status: dict | None, extra_origins: tuple[str, ...] = ()) -> KnownNames:
    """The names of the listener on the local `port`.

    serve_status (dict | None): what `tailscale serve status --json` printed; None when it was never read
    extra_origins (tuple[str, ...]): origins the configuration allows besides
    """
    reached = [("http", name, port) for name in LOOPBACK_NAMES]
    if serve_status is not None:
        reached.extend(listeners_of(serve_status, port))
    hosts: set[str] = set()
    origins = {origin.lower().rstrip("/") for origin in extra_origins}
    for scheme, name, listen_port in reached:
        forms = [f"{name}:{listen_port}".lower()]
        if DEFAULT_PORTS[scheme] == listen_port:
            forms.append(name.lower())   # a client leaves the default port out
        hosts.update(forms)
        origins.update(f"{scheme}://{form}" for form in forms)
    return KnownNames(frozenset(hosts), frozenset(origins), serve_status is not None)


def rows_outside(facts: RequestFacts, known: KnownNames) -> tuple[str, ...]:
    """The rows `facts` is outside of, all of them; empty when it is inside the table."""
    rows = []
    if facts.host not in known.hosts:
        rows.append("A")
    has_origin = facts.origin != NONE_LABEL
    is_origin_other = has_origin and facts.origin not in known.origins
    is_site_other = not has_origin and facts.fetch_site not in OWN_SITES
    if facts.method == WEBSOCKET_METHOD:
        if is_origin_other:
            rows.append("C")
    elif facts.method not in READING_METHODS:
        if is_origin_other or is_site_other:
            rows.append("B")
    elif facts.method == "GET" and facts.template in STATE_CHANGING_GETS:
        if is_origin_other or facts.fetch_site not in OWN_SITES or facts.fetch_mode == NAVIGATE:
            rows.append("D")
    if rows and not known.is_read:
        return (UNREAD,)
    return tuple(rows)
