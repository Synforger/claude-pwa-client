"""A stop signal reaches the callback and the handler that was there before, and a wait ends at it (`until_stop`)."""
from __future__ import annotations

import asyncio
import signal

import pytest

from backend._internal import stop_signal
from backend._internal.stop_signal import STOP_SIGNALS, BackendStopping, on_stop_signal, until_stop
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


# --- until_stop -----------------------------------------------------------------------------------------------------


@pytest.fixture
def running(monkeypatch):
    """The backend runs when a test begins, and again for the tests after it."""
    monkeypatch.setattr(stop_signal, "_stopping", False)


async def _answer_after(seconds: float) -> str:
    await asyncio.sleep(seconds)
    return "answered"


def test_a_wait_that_ends_before_the_stop_gives_its_result(running):
    assert run(until_stop(_answer_after(0))) == "answered"
    assert stop_signal._listeners == set()


def test_a_stop_ends_the_wait_and_cancels_it(running):
    cancelled: list[bool] = []

    async def wait() -> None:
        try:
            await asyncio.sleep(30)
        except asyncio.CancelledError:
            cancelled.append(True)
            raise

    async def scenario():
        asyncio.get_running_loop().call_later(0.02, stop_signal.end_work)
        with pytest.raises(BackendStopping):
            await asyncio.wait_for(until_stop(wait()), 5)
    run(scenario())
    assert cancelled == [True] and stop_signal._listeners == set()


def test_a_wait_that_winds_up_is_waited_for_before_the_stop_is_raised(running):
    wound_up: list[bool] = []

    async def wait() -> None:
        try:
            await asyncio.sleep(30)
        except asyncio.CancelledError:
            await asyncio.sleep(0.05)               # a typing that finishes its Enter
            wound_up.append(True)
            raise

    async def scenario():
        asyncio.get_running_loop().call_later(0.01, stop_signal.end_work)
        with pytest.raises(BackendStopping):
            await until_stop(wait())
        assert wound_up == [True]
    run(scenario())


def test_a_wait_that_begins_while_the_backend_stops_is_not_started(running):
    started: list[bool] = []

    async def wait() -> None:
        started.append(True)

    async def scenario():
        stop_signal.end_work()
        with pytest.raises(BackendStopping):
            await until_stop(wait())
    run(scenario())
    assert started == []


def test_a_backend_that_starts_again_waits_again(running):
    stop_signal.end_work()
    stop_signal.accept_work()
    assert run(until_stop(_answer_after(0))) == "answered"


def test_a_wait_that_is_cancelled_from_outside_is_cancelled_and_forgotten(running):
    cancelled: list[bool] = []

    async def wait() -> None:
        try:
            await asyncio.sleep(30)
        except asyncio.CancelledError:
            cancelled.append(True)
            raise

    async def scenario():
        outer = asyncio.ensure_future(until_stop(wait()))
        await asyncio.sleep(0.02)
        outer.cancel()
        with pytest.raises(asyncio.CancelledError):
            await outer
    run(scenario())
    assert cancelled == [True] and stop_signal._listeners == set()
