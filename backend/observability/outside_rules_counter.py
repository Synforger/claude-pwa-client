"""Count and log the requests outside the origin table. Used by `request_origin.py`."""
from __future__ import annotations

import logging

from backend.observability.log_milestones import is_milestone
from backend.observability.origin_rules import RequestFacts

logger = logging.getLogger(__name__)

# How many different tuples are kept; a limit apart from the counter of every request, so that those cannot crowd
# these out.
MAX_OUTSIDE_COUNT = 1000

_Key = tuple[str, tuple[str, ...], RequestFacts]


class OutsideRulesCounter:
    """Counts requests by app, rows and labels, and logs at the first and at each power of ten.

    Used from the event loop only, so it takes no lock.
    """

    def __init__(self) -> None:
        self._counts: dict[_Key, int] = {}
        self._overflow_count = 0

    def add(self, app: str, rows: tuple[str, ...], facts: RequestFacts) -> None:
        """Count one request outside `rows`."""
        key = (app, rows, facts)
        if key not in self._counts and len(self._counts) >= MAX_OUTSIDE_COUNT:
            self._overflow_count += 1
            if is_milestone(self._overflow_count):
                logger.info("request origin rules: outside=(overflow) count=%d", self._overflow_count)
            return
        count = self._counts.get(key, 0) + 1
        self._counts[key] = count
        if is_milestone(count):
            logger.info(
                "request origin rules: app=%s outside=%s method=%s template=%s host=%s origin=%s sec_fetch_site=%s "
                "sec_fetch_mode=%s count=%d",
                app, ",".join(rows), *facts, count,
            )
