"""Wake the screens when a ticket changes. A screen's connection holds an event from `subscribe` and builds the tickets'
picture again when it is set (`routes/unified_stream.py`); every change to a ticket's file or row calls `wake` from whatever
thread wrote it. Called by `ticket_service.py` and `ticket_peer_count.py`.
"""
from __future__ import annotations

import asyncio

_events: set[asyncio.Event] = set()
_loop: asyncio.AbstractEventLoop | None = None


def subscribe() -> asyncio.Event:
    """A new event that `wake` sets. Called in the event loop (= the loop `wake` hands to is the one it was called in)."""
    global _loop
    _loop = asyncio.get_running_loop()
    event = asyncio.Event()
    _events.add(event)
    return event


def unsubscribe(event: asyncio.Event) -> None:
    _events.discard(event)


def _set_all() -> None:
    for event in list(_events):
        event.set()


def wake() -> None:
    """Set every subscribed event. Safe from any thread; nothing happens when no screen is connected."""
    loop = _loop
    if loop is None or not _events:
        return
    try:
        loop.call_soon_threadsafe(_set_all)
    except RuntimeError:
        # the loop is closed (= the backend is stopping): there is no screen left to wake
        return
