"""When a repeated thing is worth a log line. Used by the counters of `observability/`."""
from __future__ import annotations


def is_milestone(count: int) -> bool:
    """Whether `count` is the first or a power of ten."""
    return str(count).rstrip("0") == "1"
