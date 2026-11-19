"""The names and rules the two machines of a ticket go by: which machine is a ticket's home, how a tab or a machine is
written when the ticket crosses to the other machine, which lines of a ticket never leave the home. Pure: no file, no
network, no configuration (= the caller passes the machine's own name and its peers). Used by `ticket_relay.py`,
`relay_home.py`, `ticket_pass.py` and `ticket_return.py`.
"""
from __future__ import annotations

import re
from collections.abc import Iterable

from backend.tickets import ticket_entry
from backend.tickets.ticket_id import machine_part

#: What `home_of` answers for a ticket kept on this machine (= no peer's name is empty)
HERE = ""
#: What `machine_of_party` answers for a machine that is neither this one nor the caller (= a ticket crosses between two
#: machines only)
THIRD = "\0third"
#: The lines that carry the operator's own words: they are not given to another machine (= only their kind and time are)
OPERATOR_KINDS = (ticket_entry.OPERATOR, ticket_entry.ANSWERED)

_ID_HEAD = re.compile(r"(?P<machine>.+)-\d{6}-\d{2,}")


def home_of(ticket: str, own_machine: str, peer_names: Iterable[str]) -> str | None:
    """The machine a ticket is kept on, by the machine's name at the head of its id: `HERE` for this machine (`own_machine`),
    the peer's name for a machine in `peer_names`, None when the id names neither (= `ticket_unknown`)."""
    found = _ID_HEAD.fullmatch(ticket)
    if found is None:
        return None
    head = found["machine"]
    if head == machine_part(own_machine):
        return HERE
    return next((name for name in peer_names if machine_part(name) == head), None)


def tab_of(machine: str | None, tab: str) -> str:
    """How a ticket's index names a tab: the tab's id for a tab of this machine (`machine` None), `<machine>:<id>` for a tab
    of another."""
    return tab if machine is None else f"{machine}:{tab}"


def writer_name(machine: str, tab: str, title: str) -> tuple[str, str]:
    """The `tab` and `tab_title` of a line a tab of another machine writes: `<machine>:<tab>` and `<title> @<machine>`."""
    return f"{machine}:{tab}", f"{title} @{machine}"


def seen_from(identity: str, own_machine: str, viewer_machine: str) -> str:
    """A tab's name in a ticket (`tab_of`), as the machine `viewer_machine` reads it: a tab of the viewer is written
    bare, a bare id of this machine gets this machine's name in front, and a name of any other machine stays."""
    if identity.startswith(f"{viewer_machine}:"):
        return identity.partition(":")[2]
    if identity and ":" not in identity:
        return f"{own_machine}:{identity}"
    return identity


def destination_of(to: str, peer: str | None, own_machine: str) -> tuple[str, str]:
    """A destination as the tab that passes the ticket spelled it, as `(machine, tab)`: `peer` is the machine named in
    front of the tab (None when there is none), whose tab it is; without one the tab is of the machine `own_machine`."""
    if peer is None:
        return own_machine, to
    return peer, to.partition(":")[2].strip()


def machine_of_party(named: str, own_machine: str, caller: str) -> str | None:
    """Which machine a destination or a sender named in a relayed call is on, seen from the machine that receives the call:
    None for this machine (`own_machine`), `caller` for the machine that sent the call, and `THIRD` for any other."""
    if machine_part(named) == machine_part(own_machine):
        return None
    return caller if machine_part(named) == machine_part(caller) else THIRD
