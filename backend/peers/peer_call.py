"""One call to another machine's backend (`agent_message_peers`), and what came back.

Used by `routes/agent_messages.py` (the tab list and a message handed over directly), `peer_patrol.py` (the watch) and
`outbox_flush.py` (a kept message sent again).
"""
from __future__ import annotations

import asyncio
import http.client
import json
import logging
import urllib.error
import urllib.request
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

# How long to wait for the other backend when a message is handed over. It runs its own check before it delivers, so
# this is longer than that check's own limit.
RELAY_TIMEOUT_SEC = 240.0
# How long to wait for the other machine's tab list. A machine that is down must not keep the caller waiting (= no
# check runs for a list, so a short wait is enough).
PEER_LIST_TIMEOUT_SEC = 10.0
# The paths the backends call on each other (= accepted only from a configured machine's address).
RELAYED_PATH = "/agent-messages/relayed"
PEER_TABS_PATH = "/agent-messages/tabs"


@dataclass(frozen=True)
class PeerReply:
    """What one call got back. `status` is the HTTP status, or None when no answer came.

    `connected` tells the two ways of getting no answer apart: False = the request could not be sent (connection
    refused, timed out while connecting, no route): it did not arrive. True = the request was sent and the answer
    never came (timed out while reading, connection dropped): it may have arrived."""

    status: int | None
    body: dict = field(default_factory=dict)
    connected: bool = False

    @property
    def answered(self) -> bool:
        return self.status is not None


def _call_peer(url: str, payload: dict | None, timeout: float) -> tuple[int, dict]:
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    request = urllib.request.Request(url, data=data, method="POST" if data else "GET",
                                     headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310 (= url is from the settings)
            raw, status = response.read(), response.status
    except urllib.error.HTTPError as error:
        raw, status = error.read(), error.code
    try:
        body = json.loads(raw or b"{}")
    except ValueError:
        body = {}
    return status, body if isinstance(body, dict) else {}


async def call_peer(name: str, peer: dict, path: str, payload: dict | None = None,
                    timeout: float = RELAY_TIMEOUT_SEC) -> PeerReply:
    """Call the other machine's backend once. `payload` None = GET, else POST of its JSON."""
    try:
        status, body = await asyncio.to_thread(_call_peer, peer["url"] + path, payload, timeout)
    except urllib.error.URLError as error:
        # urllib wraps what goes wrong while connecting and sending, and nothing that happens after the request left
        logger.warning("agent message: peer %s could not be reached: %s", name, error)
        return PeerReply(None, connected=False)
    except (OSError, http.client.HTTPException) as error:
        logger.warning("agent message: peer %s gave no answer after the request was sent: %s", name, error)
        return PeerReply(None, connected=True)
    return PeerReply(status, body, connected=True)
