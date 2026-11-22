"""Tells the app that the process was asked to stop, while its responses still run.

uvicorn waits for running responses before it runs the end of the lifespan, so a response with no end cannot learn of
the stop there: it is cancelled at the timeout. uvicorn puts its signal handlers in place before the lifespan starts,
so the lifespan can wrap them: the callback is scheduled on the event loop and uvicorn's handler runs as before.

A wait that is not a response of its own (= the delivery of a message, which waits for a tab to wake and for its
record to show the text) learns of the stop here: `end_work` is the callback, `until_stop` runs a wait until it is over
or the stop comes, and `BackendStopping` is what the caller then turns into the code that is true of its own stage.

Used by `backend/main.py`, and by the waits of the delivery of a message (`terminal/receipt.py`,
`terminal/input_ready.py`, `terminal/confirm.py`, `terminal/first_message.py`, `routes/agent_messages.py`).
"""
from __future__ import annotations

import asyncio
import signal
import threading
from collections.abc import Callable, Coroutine, Iterator
from contextlib import contextmanager
from types import FrameType
from typing import Any, TypeVar

STOP_SIGNALS = (signal.SIGINT, signal.SIGTERM)

_T = TypeVar("_T")

#: Whether the process was asked to stop, and the waits that `end_work` is to end (= one event per `until_stop`).
_stopping = False
_listeners: set[asyncio.Event] = set()


class BackendStopping(Exception):
    """The backend was asked to stop before what a wait waited on was over."""


def accept_work() -> None:
    """The app started: waits run until they are over."""
    global _stopping
    _stopping = False


def end_work() -> None:
    """The process is stopping: every `until_stop` ends now, and one that starts later ends at once."""
    global _stopping
    _stopping = True
    for listener in list(_listeners):
        listener.set()


def is_stopping() -> bool:
    return _stopping


async def until_stop(work: Coroutine[Any, Any, _T]) -> _T:
    """Run `work` until it is over or the backend stops. → its result. At a stop `work` is cancelled and waited for to
    wind up (= a text being typed still gets its Enter), and `BackendStopping` is raised; when the backend is stopping
    already, `work` is not started."""
    if _stopping:
        work.close()
        raise BackendStopping
    stop = asyncio.Event()
    _listeners.add(stop)
    working = asyncio.ensure_future(work)
    stopping = asyncio.ensure_future(stop.wait())
    try:
        await asyncio.wait({working, stopping}, return_when=asyncio.FIRST_COMPLETED)
    finally:
        stopping.cancel()
        _listeners.discard(stop)
        if not working.done():
            working.cancel()
            await asyncio.wait({working})
    if working.cancelled():
        raise BackendStopping
    return working.result()


@contextmanager
def on_stop_signal(callback: Callable[[], None]) -> Iterator[None]:
    """While inside, a stop signal schedules `callback` and then runs the handler that was there. Only a handler that
    is a function is wrapped (= the default action keeps ending the process). Outside the main thread, where signals
    cannot be handled, nothing is wrapped."""
    if threading.current_thread() is not threading.main_thread():
        yield
        return
    loop = asyncio.get_running_loop()
    wrapped = {}
    for number in STOP_SIGNALS:
        previous = signal.getsignal(number)
        if not callable(previous):
            continue

        def handle(received: int, frame: FrameType | None, previous: Callable = previous) -> None:
            loop.call_soon_threadsafe(callback)
            previous(received, frame)

        signal.signal(number, handle)
        wrapped[number] = (handle, previous)
    try:
        yield
    finally:
        for number, (handle, previous) in wrapped.items():
            if signal.getsignal(number) is handle:
                signal.signal(number, previous)
