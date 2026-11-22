"""The names this machine serves the client under, kept for the origin table.

`backend/main.py` runs `refresh_loop`; the middleware (`request_origin.py`) only reads what was last read, so no
request waits on `tailscale`.
"""
from __future__ import annotations

import asyncio
import logging

from backend.observability.origin_rules import KnownNames, known_names
from backend.page_url.page_url_refusal import PageUrlRefusal
from backend.page_url.tailnet import serve_status

logger = logging.getLogger(__name__)

# How often the names are read again. They change only when the operator changes what is served, and the table only
# logs, so a minute behind costs a log line at most.
REFRESH_SEC = 60.0


class ServedNames:
    """The last `tailscale serve status` that could be read, and each listener's names made from it."""

    def __init__(self) -> None:
        self._status: dict | None = None
        self._known: dict[tuple[int, tuple[str, ...]], KnownNames] = {}
        self._is_failure_logged = False

    def known(self, port: int, extra_origins: tuple[str, ...] = ()) -> KnownNames:
        """The names of the listener on the local `port`, with the origins the configuration allows it besides."""
        key = (port, extra_origins)
        found = self._known.get(key)
        if found is None:
            found = known_names(port, self._status, extra_origins)
            self._known[key] = found
        return found

    def replace(self, status: dict) -> None:
        """Take `status` as what is served now."""
        self._status = status
        self._known = {}

    def refresh(self) -> None:
        """Read what is served again. What was read before stays when that fails. Blocks on a command."""
        try:
            status = serve_status()
        except PageUrlRefusal as error:
            if not self._is_failure_logged:
                self._is_failure_logged = True
                logger.info("served names: not readable now, keeping what was read: %s", error)
            return
        self._is_failure_logged = False
        self.replace(status)

    async def refresh_loop(self) -> None:
        """Read the names at once, then every `REFRESH_SEC`."""
        while True:
            try:
                await asyncio.to_thread(self.refresh)
            except Exception:
                logger.exception("served names: the read failed")
            await asyncio.sleep(REFRESH_SEC)
