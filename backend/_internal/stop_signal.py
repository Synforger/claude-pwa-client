"""Tells the app that the process was asked to stop, while its responses still run.

uvicorn waits for running responses before it runs the end of the lifespan, so a response with no end cannot learn of
the stop there: it is cancelled at the timeout. uvicorn puts its signal handlers in place before the lifespan starts,
so the lifespan can wrap them: the callback is scheduled on the event loop and uvicorn's handler runs as before.

Used by `backend/main.py`.
"""
from __future__ import annotations

import asyncio
import signal
import threading
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from types import FrameType

STOP_SIGNALS = (signal.SIGINT, signal.SIGTERM)


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
