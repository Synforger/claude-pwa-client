"""The first message of a tier tab and the tab's name, as pure functions. Called by `tier_tabs`.

A tier tab is a tab the backend places for one tier of an agent (= `normal`, `projects/<P>`,
`projects/<P>/subprojects/<S>`). Its claude starts with an envelope the backend writes, not words of the
operator: the fixed first line (`TAB_OPEN_OPENING`) tells claude and the tools that read the terminal's
input apart from a typed message, and the `tier=` line inside the block is what the agent's launcher reads
to start in that tier (= the same shape as `<session-rollover phase="start">` and `<child-start>`).
"""

from __future__ import annotations

from backend.jsonl.jsonl_predicates import TAB_OPEN_OPENING
from backend.terminal.tier import DEFAULT_TIER

TAG = "tab-open"
#: Joins a project and a subproject in a tab's name (= the same mark the operator's tab names use)
NAME_JOINER = "・"


def envelope(tier: str) -> str:
    """The first message that starts the claude of the tab placed for `tier`."""
    return f"{TAB_OPEN_OPENING}\n<{TAG}>\ntier={tier}\n</{TAG}>"


def tab_name(tier: str, agent_name: str) -> str:
    """The name of the tab placed for `tier`: the agent's name for `normal`, else the project, and the
    project and subproject joined for a subproject (= `music`, `music・demo`)."""
    if tier == DEFAULT_TIER:
        return agent_name
    parts = tier.split("/")
    return NAME_JOINER.join(parts[1::2])
