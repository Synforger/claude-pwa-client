"""Runs a coroutine to its end on a loop of its own, for the tests that have no async runner. The loop is closed and
never made the thread's current loop, so a test run first or last leaves the loops other tests look for as they were."""
from __future__ import annotations

import asyncio
from typing import Any, Coroutine


def run(coroutine: Coroutine[Any, Any, Any]) -> Any:
    """The result of `coroutine`, run to its end."""
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coroutine)
    finally:
        loop.close()
