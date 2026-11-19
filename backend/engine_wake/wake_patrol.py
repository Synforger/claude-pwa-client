"""Wakes a speech engine when a voice that uses it opens, and puts it to rest when no voice has used it for a while.
The patrol (`wake_loop`) looks every few seconds; `ensure_awake` wakes an engine a speech is asked of. Only the engines
an agent names in `voice.engine_service` are handled (`wake_judgement.engine_services`); the others are left to their
resident services. See `docs/reference/voice.md`.

Each engine has one lock: a wake and a rest never overlap, and a speech asked while the engine is being put to rest
waits for it to be down and then wakes it. Memory only: after a restart of the backend, every engine counts as used at
the start, so none is put to rest at once.

Used by `main.py` (the loop) and `routes/voice.py` (`ensure_awake`).
"""
from __future__ import annotations

import asyncio
import logging
import os
import time
from dataclasses import dataclass, field

from backend._common import config
from backend._common.state import calls_by_conn, voices_by_conn
from backend.engine_wake import engine_service
from backend.engine_wake.wake_judgement import (
    RESTING, STARTING, STOP, WAKE, EngineService, engine_services, engine_state, next_step,
)
from backend.terminal.session_resolver import resolve_agent_cfg

logger = logging.getLogger(__name__)

# How often the patrol looks (= a voice that opens is seen within this)
LOOK_SEC = 5.0
# How long a wake waits for the engine to take a connection (= 3.7 s measured, about eight times that)
WAKE_TIMEOUT_SEC = 30.0
# How long a rest waits for the engine to refuse connections
STOP_TIMEOUT_SEC = 10.0
# How often a wake or a rest looks at the engine
POLL_SEC = 0.25
# How long the patrol waits before it tries again to wake an engine that did not wake
RETRY_SEC = 30.0


@dataclass
class _Engine:
    """What the patrol remembers of one engine."""
    last_used: float
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    failed_at: float | None = None
    failure: str = ""
    rested: bool = False        # put to rest by the patrol and not woken since
    kept_alive: bool = False    # came back by itself after a rest: its service restarts it, so it is not rested again
    phase: str | None = None    # STARTING / RESTING while a wake or a rest is under way
    up: bool | None = None      # it took a connection when last looked at; None = not looked at yet


_engines: dict[str, _Engine] = {}
_tasks: set[asyncio.Task] = set()
_warned: set[str] = set()
_started_at = time.time()


async def ensure_awake(url: str) -> None:
    """Make sure the engine at `url` takes connections before a speech is asked of it, waking it when it is down (or
    waiting for a rest under way to end, then waking it). An engine no agent names is left alone. When it does not
    wake, the speech that follows fails as an unreachable engine does."""
    service = _services().get(url.rstrip("/"))
    if service is None:
        return
    engine = _engine_of(service.url)
    engine.last_used = time.time()
    if not engine.lock.locked() and await asyncio.to_thread(engine_service.answers, service.url):
        return
    await _wake(service, engine, reason="use", warm=False)


async def engine_state_of(session_id: str) -> str | None:
    """What a screen is told of the engine the tab's agent speaks with (`wake_judgement.engine_state`); None when the
    engine is not handled here. An engine not looked at yet (= right after the backend's start) is looked at once."""
    voice = (resolve_agent_cfg(session_id) or {}).get("voice")
    url = voice.get("engine") if isinstance(voice, dict) else None
    service = _services().get(url.rstrip("/")) if isinstance(url, str) else None
    if service is None:
        return None
    engine = _engine_of(service.url)
    if engine.up is None and not engine.lock.locked():
        engine.up = await asyncio.to_thread(engine_service.answers, service.url)
    return engine_state(phase=engine.phase, up=bool(engine.up),
                        waiting_to_retry=engine.failed_at is not None and time.time() - engine.failed_at < RETRY_SEC)


async def look() -> None:
    """Look at every engine once: wake the ones a voice uses, put to rest the ones no voice has used for their idle
    time."""
    services = _services()
    open_urls = _open_engine_urls(services)
    now = time.time()
    for url, service in services.items():
        engine = _engine_of(url)
        if url in open_urls:
            engine.last_used = now
        busy = engine.lock.locked()
        answers = False if busy else await asyncio.to_thread(engine_service.answers, url)
        if not busy:
            engine.up = answers
        if answers and engine.rested and not engine.kept_alive:
            engine.kept_alive = True
            logger.warning("engine wake: label=%s came back by itself after a rest; its service keeps it alive, so it "
                           "is not rested again until the backend restarts", service.label)
        step = next_step(voice_open=url in open_urls, answers=answers, busy=busy, kept_alive=engine.kept_alive,
                         waiting_to_retry=engine.failed_at is not None and now - engine.failed_at < RETRY_SEC,
                         idle_minutes=service.idle_minutes,
                         quiet_minutes=(now - max(engine.last_used, _started_at)) / 60)
        if step == WAKE:
            _spawn(_wake(service, engine, reason="voice_open", warm=True))
        elif step == STOP:
            _spawn(_stop(service, engine))


async def wake_loop(interval_sec: float = LOOK_SEC) -> None:
    """Look over the engines every `interval_sec`. The end-to-end test backend has no engines to wake: it returns."""
    if os.environ.get("CPC_E2E") == "1":
        return
    logger.info("engine wake loop started (interval=%ds)", interval_sec)
    try:
        while True:
            await asyncio.sleep(interval_sec)
            try:
                await look()
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("engine wake look failed")
    except asyncio.CancelledError:
        logger.info("engine wake loop cancelled")
        raise


async def _wake(service: EngineService, engine: _Engine, *, reason: str, warm: bool) -> bool:
    """Start the engine's service and wait until it takes connections. → whether it does."""
    async with engine.lock:
        if await asyncio.to_thread(engine_service.answers, service.url):
            engine.up = True
            return True
        engine.phase = STARTING
        try:
            return await _start(service, engine, reason=reason, warm=warm)
        finally:
            engine.phase = None


async def _start(service: EngineService, engine: _Engine, *, reason: str, warm: bool) -> bool:
    """The body of a wake, under the engine's lock."""
    started = time.monotonic()
    failure = await asyncio.to_thread(engine_service.start, service.label)
    if not failure and not await _until(service.url, up=True, timeout_sec=WAKE_TIMEOUT_SEC):
        failure = f"it did not take connections within {WAKE_TIMEOUT_SEC:.0f}s"
    if failure:
        engine.failed_at, engine.up = time.time(), False
        if failure != engine.failure:
            logger.warning("engine wake: could not start label=%s: %s", service.label, failure)
        engine.failure = failure
        return False
    warmed = warm and await asyncio.to_thread(engine_service.warm, service.url, service.speaker)
    engine.failed_at, engine.failure, engine.last_used, engine.rested = None, "", time.time(), False
    engine.up = True
    logger.info("engine wake: started label=%s reason=%s took=%.1fs warmed=%s", service.label, reason,
                time.monotonic() - started, warmed)
    return True


async def _stop(service: EngineService, engine: _Engine) -> None:
    """Stop the engine's service and wait until it refuses connections."""
    async with engine.lock:
        engine.phase = RESTING
        try:
            await _rest(service, engine)
        finally:
            engine.phase = None


async def _rest(service: EngineService, engine: _Engine) -> None:
    """The body of a rest, under the engine's lock."""
    quiet_minutes = (time.time() - engine.last_used) / 60
    failure = await asyncio.to_thread(engine_service.stop, service.label)
    if failure:
        logger.warning("engine wake: could not stop label=%s: %s", service.label, failure)
        return
    down = await _until(service.url, up=False, timeout_sec=STOP_TIMEOUT_SEC)
    engine.rested, engine.up = True, not down
    logger.info("engine wake: stopped label=%s idle_min=%.0f down=%s", service.label, quiet_minutes, down)


async def _until(url: str, *, up: bool, timeout_sec: float) -> bool:
    """Wait until the engine takes (`up`) or refuses connections. → whether it did within `timeout_sec`."""
    deadline = time.monotonic() + timeout_sec
    while True:
        if await asyncio.to_thread(engine_service.answers, url) == up:
            return True
        if time.monotonic() >= deadline:
            return False
        await asyncio.sleep(POLL_SEC)


def _services() -> dict[str, EngineService]:
    services, warnings = engine_services(config.AGENTS)
    for warning in warnings:
        if warning not in _warned:
            _warned.add(warning)
            logger.warning("engine wake: %s", warning)
    return services


def _open_engine_urls(services: dict[str, EngineService]) -> set[str]:
    """The engines a voice uses now: of every tab with a screen's 🔊 or 🎙 on or a call connected, the engine its
    agent's voice points at."""
    sessions = {sid for sids in voices_by_conn.values() for sid in sids} | set(calls_by_conn.values())
    urls = set()
    for session_id in sessions:
        voice = (resolve_agent_cfg(session_id) or {}).get("voice")
        engine = voice.get("engine") if isinstance(voice, dict) else None
        if isinstance(engine, str) and engine.rstrip("/") in services:
            urls.add(engine.rstrip("/"))
    return urls


def _engine_of(url: str) -> _Engine:
    if url not in _engines:
        _engines[url] = _Engine(last_used=_started_at)
    return _engines[url]


def _spawn(coroutine) -> None:
    task = asyncio.create_task(coroutine)
    _tasks.add(task)
    task.add_done_callback(_tasks.discard)
