"""Whether the account fallback moves a tab, brings it back, or leaves it. Pure: it takes the facts and answers, and
reads no file, no log and no state.

The usage of the account a tab belongs to is judged by `usage.limit_state`, against the line of the 5 hours and the
line of the 7 days of the day (`seven_day_line_pct`); a tab may be moved or brought back only at
a break, which `sleep_judgement.judge` (= asked by hand) decides, or which a turn that a usage limit stopped is.

The prompt cache of an account lasts `PROMPT_CACHE_LIFETIME_MIN` and is kept per account, so a tab that runs on another
account reads its whole conversation again at its first message there. That is why a tab with a warm cache is moved
only when its account is at its line, and a tab with a cold cache (`cold_reasons`) is moved already `ahead_pct` before
the line (`home_is_near`) and is brought back once the account is clear of that width. A moved tab is also brought
back at once, warm or not, when the account it runs on has reached its own line (`target_over_line`) and the account
it belongs to has not. No tab is moved to an account at its own line, not even from an account at its line: with both
accounts at their lines the tab stays where it is, and the account hold stops it there (`account_hold`).

A tab that keeps answering is never at a break, so it is asked once to come to one (`should_ask_to_pause`) when it
must move whatever its cache is (`urgent_move`); the request is given up on after `PAUSE_WAIT_SEC` (`pause_overdue`).

Used by `fallback_patrol.py`.
"""
from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Iterable

from backend.account_fallback.fallback_settings import AT_PCT_MIN, WEEKDAYS, FallbackRule
from backend.sleep.sleep_judgement import TURN_OPEN
from backend.usage.limit_state import limit_state


# How long a tab that was asked to come to a break is waited for before the patrol says it gave up on the request.
PAUSE_WAIT_SEC = 600
# How long the prompt cache of a conversation lasts: a tab quiet for this long reads its conversation at full price at
# its next message wherever it runs.
PROMPT_CACHE_LIFETIME_MIN = 60

# Why a tab's cache counts as cold (= logged as they are).
QUIET = "quiet"


class Move(str, Enum):
    """What to do with a tab."""
    STAY = "stay"
    MOVE = "move"        # from the account it belongs to, to the account its fallback names
    RETURN = "return"    # from where it runs now, to the account it belongs to


def seven_day_line_pct(rule: FallbackRule, now: float) -> int:
    """The line of the 7 days at time `now`: the one `rule` names for that day of the week (by the local time of this
    machine, so it changes at 0:00), `at_pct` when it names none."""
    return rule.seven_day_at_pct.get(WEEKDAYS[datetime.fromtimestamp(now).weekday()], rule.at_pct)


def home_is_limited(rows: Iterable[dict], rule: FallbackRule, now: float) -> bool | None:
    """Whether the usage of the account of `rule` is at its line. None when the log says nothing about the account."""
    state = limit_state(rows, rule.from_account, rule.at_pct, now, seven_day_line_pct=seven_day_line_pct(rule, now))
    return None if state is None else state.at_limit


def _ahead_line(line: int, rule: FallbackRule) -> int:
    """`line` moved `rule.ahead_pct` points down, and never below the lowest line that can be set."""
    return max(line - rule.ahead_pct, AT_PCT_MIN)


def home_is_near(rows: Iterable[dict], rule: FallbackRule, now: float) -> bool | None:
    """Whether the usage of the account of `rule` is within `rule.ahead_pct` of its line (or past it): the 5 hours at
    `at_pct - ahead_pct` or more, or the 7 days at the line of the day minus `ahead_pct` or more, that window not
    reset. Without an `ahead_pct` this is `home_is_limited`. None when the log says nothing about the account."""
    state = limit_state(rows, rule.from_account, _ahead_line(rule.at_pct, rule),
                        now, seven_day_line_pct=_ahead_line(seven_day_line_pct(rule, now), rule))
    return None if state is None else state.at_limit


def cold_reasons(*, quiet_minutes: float | None) -> tuple[str, ...]:
    """Why the cache of a running tab is cold, empty when it is not (= or it is not known): the tab has been quiet for
    `PROMPT_CACHE_LIFETIME_MIN`. A tab that sleeps is cold by itself. A tab whose context is at the rollover's line is
    not: moving it would read its long conversation again on the other account, while the rollover starts its next
    conversation on the right account for nothing (`account_hold/new_conversation_account.py`)."""
    return (QUIET,) if quiet_minutes is not None and quiet_minutes >= PROMPT_CACHE_LIFETIME_MIN else ()


def returns_over_target_line(*, current: str, home: str, rule: FallbackRule | None, limited: bool | None,
                             target_over_line: bool | None) -> bool:
    """Whether a moved tab goes back at once: the account it runs on is at its own line (`target_over_line`) and the
    account it belongs to is not at its line. When that account is at its line too, the tab stays (and is stopped
    there); when that is not known, it stays."""
    return current != home and rule is not None and limited is False and target_over_line is True


def decide(*, current: str, home: str, rule: FallbackRule | None, limited: bool | None, at_break: bool,
           pinned: bool = False, near: bool | None = None, cold: bool = True,
           target_over_line: bool | None = None) -> Move:
    """What to do with a tab that runs on `current` and belongs to `home` (= the same account unless it was moved).

    `rule` is the fallback of `home` (None when it has none), `limited` whether the usage of `home` is at the rule's
    line and `near` whether it is within `ahead_pct` of it (None = `limited`, i.e. no width; for either, None = not
    known), `cold` whether the cache of the tab is cold, `target_over_line` whether the account the tab would be moved
    to, or runs on now, is at its own line, `at_break` whether the tab may be interrupted now, `pinned` whether the
    operator keeps the tab on its own account.

    A tab on its own account moves when the account is limited, unless it is pinned; when the account is only near its
    line, a tab with a cold cache moves. Either way only if the account it would move to is not at its line (= with
    both at their lines it stays, and the account hold stops it). A moved tab is brought
    back when its fallback has gone from the configuration, it is pinned (= even while the account is limited), or the
    account it runs on has reached its line and the account it belongs to has not; and, once the account it belongs
    to is not near its line any more, when its cache is cold. Whatever is not known leaves the tab where it is."""
    near = limited if near is None else near
    if current != home:
        returns = (pinned or rule is None or (near is False and cold) or
                   returns_over_target_line(current=current, home=home, rule=rule, limited=limited,
                                            target_over_line=target_over_line))
        return Move.RETURN if returns and at_break else Move.STAY
    if rule is None or pinned or not at_break:
        return Move.STAY
    if (limited is True or (near is True and cold)) and target_over_line is not True:
        return Move.MOVE
    return Move.STAY


def urgent_move(*, current: str, home: str, rule: FallbackRule | None, limited: bool | None,
                target_over_line: bool | None, pinned: bool) -> Move:
    """The move a tab needs whatever its cache is: off an account at its line, or off an account that has reached its
    own line. Whatever the patrol waits for a cold cache to do is not urgent, and neither is what a pinned tab or a
    tab whose fallback is gone does (= they come back at a break without being asked)."""
    if pinned or rule is None:
        return Move.STAY
    return decide(current=current, home=home, rule=rule, limited=limited, at_break=True, cold=False,
                  target_over_line=target_over_line)


def should_ask_to_pause(*, wanted: Move, blocked_by: tuple[str, ...], stopped_by_limit: bool,
                        asked_at: float | None) -> bool:
    """Whether the tab is asked to come to a break: it must move whatever its cache is (`wanted` is `urgent_move`),
    it is held because claude is answering (`turn_open` among `blocked_by`; a tab held only by commands, wake-ups or a
    call is not answering), no usage limit stopped it (that stop is its break) and it was not asked during this stay
    above the line (`asked_at` = None)."""
    return wanted is not Move.STAY and TURN_OPEN in blocked_by and not stopped_by_limit and asked_at is None


def pause_overdue(asked_at: float, now: float) -> bool:
    """Whether a tab asked at `asked_at` has had `PAUSE_WAIT_SEC` and still has not come to a break."""
    return now - asked_at >= PAUSE_WAIT_SEC
