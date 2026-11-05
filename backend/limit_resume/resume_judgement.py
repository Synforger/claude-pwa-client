"""Whether a tab that a usage limit stopped is told to carry on. Pure: it takes the stop, the state of the account
and what was already done, and reads no file, no log and no state.

The account's state is judged by `usage.limit_state`, against the line the account moves its tabs away at when it has
an account fallback (`account_fallback`), or against 100% when it has none: that is, "the usage came down from where it
stopped the tab". While an account with a fallback is at its line its tabs are the fallback's to move; this is for the
tabs it could not move, once the usage is over.

Used by `resume_patrol.py`.
"""
from __future__ import annotations

from backend.sleep.record_facts import LimitStop
from backend.usage.limit_state import LimitState

# The line of an account without an account fallback: the usage that stops a tab.
NO_FALLBACK_LINE_PCT = 100


def should_resume(*, stop: LimitStop, resumed: str | None, state: LimitState | None, seen_at_limit: bool) -> bool:
    """Whether to tell the tab to carry on. `stop` is the stop its conversation ends in, `resumed` the uuid of the stop
    it was already told about, `state` what the log says of its account now (None = nothing), `seen_at_limit` whether
    this stop was seen while the account was at its line.

    Yes when the account is no longer at its line and that is shown by what happened after the stop: a window that
    was at the line reset after the stop, or a newer row of the log shows the usage under the line having seen it at
    the line. A stop the usage never explained (= not seen at the line, no reset after it) is not answered, since
    the same stop would come again."""
    if resumed == stop.uuid or state is None or state.at_limit:
        return False
    reset_after_stop = state.last_reset is not None and state.last_reset > stop.at
    row_after_stop = seen_at_limit and state.read_at is not None and state.read_at >= stop.at
    return reset_after_stop or row_after_stop
