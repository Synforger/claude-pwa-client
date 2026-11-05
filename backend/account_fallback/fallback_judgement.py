"""Whether the account fallback moves a tab, brings it back, or leaves it. Pure: it takes the facts and answers, and
reads no file, no log and no state.

The usage of the account a tab belongs to is judged by `usage.limit_state`; a tab may be moved or brought back only at
a break, which `sleep_judgement.judge` (= asked by hand) decides, or which a turn that a usage limit stopped is.

A tab that keeps answering is never at a break, so it is asked once to come to one (`should_ask_to_pause`); the
request is given up on after `PAUSE_WAIT_SEC` (`pause_overdue`).

Used by `fallback_patrol.py`.
"""
from __future__ import annotations

from enum import Enum
from typing import Iterable

from backend.account_fallback.fallback_settings import FallbackRule
from backend.sleep.sleep_judgement import TURN_OPEN
from backend.usage.limit_state import limit_state


# How long a tab that was asked to come to a break is waited for before the patrol says it gave up on the request.
PAUSE_WAIT_SEC = 600


class Move(str, Enum):
    """What to do with a tab."""
    STAY = "stay"
    MOVE = "move"        # from the account it belongs to, to the account its fallback names
    RETURN = "return"    # from where it runs now, to the account it belongs to


def home_is_limited(rows: Iterable[dict], rule: FallbackRule, now: float) -> bool | None:
    """Whether the usage of the account of `rule` is at its line. None when the log says nothing about the account."""
    state = limit_state(rows, rule.from_account, rule.at_pct, now)
    return None if state is None else state.at_limit


def decide(*, current: str, home: str, rule: FallbackRule | None, limited: bool | None, at_break: bool,
           pinned: bool = False) -> Move:
    """What to do with a tab that runs on `current` and belongs to `home` (= the same account unless it was moved).

    `rule` is the fallback of `home` (None when it has none), `limited` whether the usage of `home` is at the rule's
    line (None = not known), `at_break` whether the tab may be interrupted now, `pinned` whether the operator keeps
    the tab on its own account. A tab on its own account moves when the account is limited, unless it is pinned. A
    moved tab is brought back when the account is not limited any more, its fallback has gone from the configuration,
    or it is pinned (= even while the account is limited). Whatever is not known leaves the tab where it is."""
    if current != home:
        returns = pinned or rule is None or limited is False
        return Move.RETURN if returns and at_break else Move.STAY
    return Move.MOVE if rule is not None and limited is True and at_break and not pinned else Move.STAY


def should_ask_to_pause(*, wanted: Move, blocked_by: tuple[str, ...], stopped_by_limit: bool,
                        asked_at: float | None) -> bool:
    """Whether the tab is asked to come to a break: it is wanted on the fallback account (`wanted` = MOVE), it is held
    because claude is answering (`turn_open` among `blocked_by`; a tab held only by commands, wake-ups or a call is
    not answering), no usage limit stopped it (that stop is its break) and it was not asked during this stay above
    the line (`asked_at` = None)."""
    return wanted is Move.MOVE and TURN_OPEN in blocked_by and not stopped_by_limit and asked_at is None


def pause_overdue(asked_at: float, now: float) -> bool:
    """Whether a tab asked at `asked_at` has had `PAUSE_WAIT_SEC` and still has not come to a break."""
    return now - asked_at >= PAUSE_WAIT_SEC
