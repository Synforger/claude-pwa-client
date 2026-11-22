"""A stop signal reaches the callback and the handler that was there before."""
from __future__ import annotations

import asyncio
import signal

import pytest

from backend._internal.stop_signal import STOP_SIGNALS, on_stop_signal
from backend.tests.async_run import run


@pytest.fixture
def handlers():
    """What the handlers in place received; the real ones are put back afterwards."""
    received: list[int] = []

    def before(number, _frame):
        received.append(number)

    real = {number: signal.signal(number, before) for number in STOP_SIGNALS}
    yield received, before
    for number, handler in real.items():
        signal.signal(number, handler)


@pytest.mark.parametrize("number", STOP_SIGNALS)
def test_a_stop_signal_runs_the_callback_and_the_handler_that_was_there(handlers, number):
    received, before = handlers
    told: list[bool] = []

    async def scenario():
        with on_stop_signal(lambda: told.append(True)):
            signal.raise_signal(number)
            await asyncio.sleep(0)
            await asyncio.sleep(0)
        assert signal.getsignal(number) is before

    run(scenario())
    assert (received, told) == ([number], [True])


def test_the_default_action_is_left_as_it_is(handlers):
    async def scenario():
        signal.signal(signal.SIGTERM, signal.SIG_DFL)
        with on_stop_signal(lambda: None):
            assert signal.getsignal(signal.SIGTERM) is signal.SIG_DFL

    run(scenario())


def test_two_callbacks_one_inside_the_other_both_run(handlers):
    received, before = handlers
    told: list[str] = []

    async def scenario():
        with on_stop_signal(lambda: told.append("outer")), on_stop_signal(lambda: told.append("inner")):
            signal.raise_signal(signal.SIGTERM)
            await asyncio.sleep(0)
            await asyncio.sleep(0)
        assert signal.getsignal(signal.SIGTERM) is before

    run(scenario())
    assert received == [signal.SIGTERM] and sorted(told) == ["inner", "outer"]
