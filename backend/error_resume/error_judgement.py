"""Whether the client tells a tab whose turn a passing API error ended to carry on. Pure: it takes what was read about
the tab and answers; it reads no file, no process and no state.

The answers:
- `NONE`:     there is no stop to answer, or it was given up on already.
- `WAIT`:     the stop is the client's, but not yet: the wait after the error has not passed, the tab is still busy
              (Claude Code keeps a process for a few minutes after a turn), or a message was sent a moment ago.
- `SEND`:     send the message to carry on now.
- `GIVE_UP`:  the messages did not help (or did not get through): tell the tab's parent, or the operator.
- `NOT_MINE`: the client does not answer this stop (another feature carries the tab on, or nothing may).
The child watch keeps quiet about a child while the answer is `WAIT` or `SEND`.

Used by `error_sensors.py`.
"""
from __future__ import annotations

from backend._common.state import ErrorResumeMark
from backend.sleep.record_facts import ErrorStop

NONE = "none"
WAIT = "wait"
SEND = "send"
GIVE_UP = "give_up"
NOT_MINE = "not_mine"

# The wait (seconds) after the error row before the message, by the streak: the first gives a moment for the network
# to come back and for the operator to type themselves; the later ones keep the client from typing into an outage of
# the API over and over.
WAITS_BY_STREAK_SEC = (30, 5 * 60, 15 * 60)
# The streak at which the client gives up: as many messages as there are waits were sent, and each turn they started
# ended in a passing API error again.
STREAK_LIMIT = len(WAITS_BY_STREAK_SEC)
# An error row older than this is not answered: the patrol answers within the waits above, so only a backend that was
# down longer, or a stop from before this feature ran, leaves an older one, and waking such tabs all at once is wrong.
MAX_AGE_SEC = 60 * 60
# How long after a message (from when sending it returned) the stop may still stand: the message's own row ends the
# stop as soon as Claude takes it, so a stop standing longer means it did not get through.
UNTAKEN_SEC = 3 * 60
# How many times one stop is sent the message before the client gives up on getting it through.
SEND_LIMIT = 2


def judge(*, stop: ErrorStop | None, streak: int, resumed: ErrorResumeMark | None, gave_up: str | None,
          takes_asks: bool, reported: bool, held: bool, may_run: bool, owes_other: bool, asleep: bool,
          claude_runs: bool, at_break: bool, now: float) -> str:
    """What to do about the tab. `stop` is the passing API error its conversation ends in, `streak` how many messages
    of the client in a row already met one (`RecordFacts.error_streak`), `resumed` the client's last message to it and
    `gave_up` the stop it gave up on. `takes_asks` is a tab set up for asks, `reported` a child that reported its work
    done, `held` a tab the account hold stopped, `may_run` whether its account lets it run now, `owes_other` whether
    another message to carry on is owed to it or kept for it. `asleep`, `claude_runs` and `at_break` say how it is now."""
    if stop is None or gave_up == stop.uuid:
        return NONE
    if now - stop.at > MAX_AGE_SEC or takes_asks or reported or held or not may_run or owes_other:
        return NOT_MINE
    if not asleep:
        if not claude_runs:
            return NOT_MINE
        if not at_break:
            return WAIT
    if resumed is not None and resumed.stop == stop.uuid:
        if now - resumed.sent_at < UNTAKEN_SEC:
            return WAIT
        if resumed.sent_count >= SEND_LIMIT:
            return GIVE_UP
    if streak >= STREAK_LIMIT:
        return GIVE_UP
    if now - stop.at < WAITS_BY_STREAK_SEC[streak]:
        return WAIT
    return SEND
