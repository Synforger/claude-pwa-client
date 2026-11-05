"""Whether the account fallback moves a tab, brings it back, or leaves it. Pure: it takes the facts and answers, and
reads no file, no log and no state.

The usage of the account a tab belongs to is judged by `usage.limit_state`; a tab may be moved or brought back only at
a break, which `sleep_judgement.judge` (= asked by hand) decides, or which a turn that a usage limit stopped is.

Used by `fallback_patrol.py`.
"""
from __future__ import annotations

from enum import Enum
from typing import Iterable

from backend.account_fallback.fallback_settings import FallbackRule
from backend.usage.limit_state import limit_state


class Move(str, Enum):
    """What to do with a tab."""
    STAY = "stay"
    MOVE = "move"        # from the account it belongs to, to the account its fallback names
    RETURN = "return"    # from where it runs now, to the account it belongs to


def home_is_limited(rows: Iterable[dict], rule: FallbackRule, now: float) -> bool | None:
    """Whether the usage of the account of `rule` is at its line. None when the log says nothing about the account."""
    state = limit_state(rows, rule.from_account, rule.at_pct, now)
    return None if state is None else state.at_limit


def decide(*, current: str, home: str, rule: FallbackRule | None, limited: bool | None, at_break: bool) -> Move:
    """What to do with a tab that runs on `current` and belongs to `home` (= the same account unless it was moved).

    `rule` is the fallback of `home` (None when it has none), `limited` whether the usage of `home` is at the rule's
    line (None = not known), `at_break` whether the tab may be interrupted now. A tab on its own account moves when
    the account is limited. A moved tab is brought back when the account is not limited any more, or its fallback has
    gone from the configuration. Whatever is not known leaves the tab where it is."""
    if current != home:
        returns = rule is None or limited is False
        return Move.RETURN if returns and at_break else Move.STAY
    return Move.MOVE if rule is not None and limited is True and at_break else Move.STAY
