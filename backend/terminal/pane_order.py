"""The order of what the backend does to a tab's pane, for work that waits on tmux in a thread.

tmux and the process table are read and typed into in threads, so that a slow machine stops one tab's request and not
every one. Two things must then be held by hand:

- keys reach a tab in the order they were asked for (`in_typing_order`)
- from the look for a claude in a pane to the launch typed into it, one request at a time (`deciding_launch`): two
  that both saw a shell would both type a launch

Used by `terminal/` and by the route of the messages between tabs.
"""
from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Callable, Coroutine
from contextlib import asynccontextmanager
from typing import Any, TypeVar
from weakref import WeakValueDictionary

Result = TypeVar("Result")

# A lock lives while someone holds it or waits for it, so a closed tab leaves none behind.
_typing_locks: WeakValueDictionary[str, asyncio.Lock] = WeakValueDictionary()
_launch_locks: WeakValueDictionary[str, asyncio.Lock] = WeakValueDictionary()
# How many decide a tab's launch or wait to: the lock alone looks free between one holder and the next.
_deciders: dict[str, int] = {}


async def run_to_end(work: Coroutine[Any, Any, Result]) -> Result:
    """Run `work` to its end even when the caller is cancelled, and only then let the cancellation through."""
    task = asyncio.ensure_future(work)
    try:
        return await asyncio.shield(task)
    except asyncio.CancelledError:
        await asyncio.wait({task})
        raise


async def in_typing_order(session_id: str, typing: Callable[[], Result]) -> Result:
    """Run `typing` (= what types into the tab, and blocks) in a thread, after what was asked for this tab before it.
    What one call types is not cut into by another, and a call that began is not left half typed."""
    lock = _lock_of(_typing_locks, session_id)

    async def typed() -> Result:
        async with lock:
            return await asyncio.to_thread(typing)

    return await run_to_end(typed())


@asynccontextmanager
async def deciding_launch(session_id: str) -> AsyncIterator[bool]:
    """Hold the tab from the look for its claude to the launch typed for it, after who asked before. Yields whether
    there was anyone to wait for."""
    ahead = _deciders.get(session_id, 0)
    _deciders[session_id] = ahead + 1
    try:
        async with _lock_of(_launch_locks, session_id):
            yield ahead > 0
    finally:
        left = _deciders[session_id] - 1
        if left:
            _deciders[session_id] = left
        else:
            del _deciders[session_id]


def is_deciding_launch(session_id: str) -> bool:
    """Whether someone is now between the look for the tab's claude and the launch, or waits to be."""
    return session_id in _deciders


def _lock_of(locks: WeakValueDictionary[str, asyncio.Lock], session_id: str) -> asyncio.Lock:
    lock = locks.get(session_id)
    if lock is None:
        lock = asyncio.Lock()
        locks[session_id] = lock
    return lock
