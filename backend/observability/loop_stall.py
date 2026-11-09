"""Report a backend that stopped answering: when the event loop has not run for `STALL_SEC`, the stack of every
thread is written to `loop-stall.log` in the log folder, and once the loop runs again one line in the error log says
how long it stood still.

The stacks are written by faulthandler's own C thread, which needs neither the event loop nor the GIL. It catches a
loop held by a call that blocks it and a thread that keeps the GIL in a long C call alike: in both, no request is
answered and no other Python thread runs, and the stack shows which call it was.

Used by `backend/main.py` (= started with the other loops of the lifespan).
"""
from __future__ import annotations

import asyncio
import faulthandler
import logging
import time
from datetime import datetime
from pathlib import Path

logger = logging.getLogger(__name__)

# How long the loop may stand still before its stacks are written. Longer than any wait the loop is meant to have
# (its own sleeps are a second or two), and shorter than the stops seen under load (a minute and more).
STALL_SEC: float = 15.0
# How often the loop winds the clock back.
BEAT_SEC: float = 1.0
STALL_FILE_NAME = "loop-stall.log"


def stall_seconds(slept_from: float, woke_at: float, beat_sec: float) -> float:
    """How long the loop stood still around one beat: the time past the beat it slept for."""
    return max(0.0, woke_at - slept_from - beat_sec)


async def loop_stall_watch(log_dir: Path, *, stall_sec: float = STALL_SEC, beat_sec: float = BEAT_SEC) -> None:
    """Wind faulthandler's clock back every `beat_sec` while the loop runs; a stop of `stall_sec` or more leaves the
    stacks in `<log_dir>/loop-stall.log` and, when the loop is back, a warning naming the time and the length."""
    path = log_dir / STALL_FILE_NAME
    # faulthandler writes to the file's descriptor from its own thread, so the file stays open while the watch runs.
    with path.open("a", encoding="utf-8") as out:
        logger.info("loop_stall_watch started (stall=%.0fs) -> %s", stall_sec, path)
        try:
            while True:
                faulthandler.dump_traceback_later(stall_sec, repeat=False, file=out, exit=False)
                slept_from = time.monotonic()
                await asyncio.sleep(beat_sec)
                stood = stall_seconds(slept_from, time.monotonic(), beat_sec)
                if stood >= stall_sec:
                    out.write(f"--- the stacks above: loop stood still {stood:.0f}s, back at "
                              f"{datetime.now().isoformat(timespec='seconds')} ---\n")
                    out.flush()
                    logger.warning("loop stall: the event loop stood still %.0fs; the stacks are in %s", stood, path)
        finally:
            faulthandler.cancel_dump_traceback_later()
