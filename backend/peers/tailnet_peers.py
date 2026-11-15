"""Whether another machine shows on the tailnet, and when it was last seen there (= `tailscale status --json`).

Used by `peer_health.py` when a machine does not answer: a machine that is off the tailnet is asleep or has lost power or
network, one that is on it but does not answer has a backend that is not running. The command is the one
`page_url/tailnet.py` finds.
"""
from __future__ import annotations

import json
import logging
import os
import subprocess

from backend.page_url.page_url_refusal import PageUrlRefusal
from backend.page_url.tailnet import CLI_MODE_ENV, tailscale_command

logger = logging.getLogger(__name__)

# How long the local daemon may take to answer (= it answers from memory, in well under a second).
STATUS_TIMEOUT_SEC = 10.0
# What Tailscale prints as the last-seen time of a machine it has never seen (= the zero time).
_NEVER_SEEN_PREFIX = "0001-01-01"


def _unknown() -> dict:
    return {"online": None, "last_seen": None}


def peer_status(address: str) -> dict:
    """`{"online": bool | None, "last_seen": <ISO time> | None}` of the machine whose tailnet address is `address`.
    `online` is None (and `last_seen` None) when it cannot be told: the command is missing or fails, or no machine of
    the tailnet has this address. Blocking."""
    try:
        done = subprocess.run([tailscale_command(), "status", "--json"], capture_output=True, text=True,
                              errors="replace", timeout=STATUS_TIMEOUT_SEC, stdin=subprocess.DEVNULL,
                              env={**os.environ, **CLI_MODE_ENV})
    except (PageUrlRefusal, OSError, subprocess.TimeoutExpired) as error:
        logger.info("tailnet status could not be read: %s", error)
        return _unknown()
    if done.returncode != 0:
        logger.info("tailnet status failed (exit %d)", done.returncode)
        return _unknown()
    try:
        status = json.loads(done.stdout)
    except ValueError:
        return _unknown()
    peers = status.get("Peer") if isinstance(status, dict) else None
    for node in (peers.values() if isinstance(peers, dict) else ()):
        if isinstance(node, dict) and address in (node.get("TailscaleIPs") or ()):
            last_seen = node.get("LastSeen")
            seen = last_seen if isinstance(last_seen, str) and not last_seen.startswith(_NEVER_SEEN_PREFIX) else None
            online = node.get("Online")
            return {"online": online if isinstance(online, bool) else None, "last_seen": seen}
    return _unknown()
