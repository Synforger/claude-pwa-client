"""Whether a tab's claude may be put to sleep. Pure: it takes the facts the sensors read and answers with the
conditions that are not met; it reads no file, no process and no state.

A tab may sleep only when every condition holds. Each condition that fails is returned, so the log can say why a
quiet tab was left awake. The sensors read the cheap facts first and stop at the first condition that fails, so a
fact that was not read is `None` here and its condition is skipped; an answer with no failing condition is always
about facts that were all read.

A parent tab can also put one of its children to sleep at once (`tabs sleep`). That sleep does not wait for the
quiet minutes, and it does not leave a child above the rollover's line awake: the parent knows the child is waiting,
and the rollover takes the child over once a message wakes it. Every other condition holds as it does for the patrol.

Used by `sleep_patrol.py` and, once more just before the claude is ended, by `sleeper.py`.
"""
from __future__ import annotations

from dataclasses import dataclass

from backend.sleep.record_facts import RecordFacts

# The reasons a tab is left awake (= logged as they are).
CLAUDE_NOT_RUNNING = "claude_not_running"
STARTING = "starting"
TURN_OPEN = "turn_open"
NO_RECORD = "no_record"
NOT_QUIET = "not_quiet"
CONTEXT_AT_ROLLOVER_LINE = "context_at_rollover_line"
PROCESSES_RUNNING = "processes_running"
WAKEUP_SCHEDULED = "wakeup_scheduled"
CRON_SCHEDULED = "cron_scheduled"
AWAITING_TOOL_RESULT = "awaiting_tool_result"
VOICE_CALL = "voice_call"
ROLLING_OVER = "rolling_over"

# The conditions a sleep asked for by hand does not look at (= the parent decides the child is done).
NOT_ASKED_BY_HAND = frozenset({NOT_QUIET, CONTEXT_AT_ROLLOVER_LINE})
# The conditions a tab whose turn a usage limit stopped does not look at: what such a stop leaves looking like work in
# progress (the turn that never closed, the call that will never get its result, the start that got no answer). What
# is really running under it (commands, wake-ups, cron jobs, a call) is still looked at.
LEFT_BY_A_LIMIT_STOP = frozenset({TURN_OPEN, AWAITING_TOOL_RESULT, STARTING})
# The conditions that pass by themselves within moments of a report: the child finishing its last answer and the
# commands of that answer. A sleep asked for by hand waits for these, and answers with the others at once.
PASSING = frozenset({STARTING, TURN_OPEN, PROCESSES_RUNNING, AWAITING_TOOL_RESULT})

# Language tools that stay under a claude whether or not it works. Matched against the name of a process and the
# names in its command line (= a tool run by node shows as `node`, with its own name in the arguments). Nothing
# below such a tool is looked at.
LANGUAGE_TOOLS = frozenset({
    "clangd", "pyright-langserver", "typescript-language-server", "gopls", "rust-analyzer", "sourcekit-lsp",
})


@dataclass(frozen=True)
class ProcessNode:
    """One process under a claude: the names it goes by, and its children."""
    names: tuple[str, ...]
    children: tuple["ProcessNode", ...] = ()


def foreign_processes(nodes: tuple[ProcessNode, ...]) -> tuple[str, ...]:
    """The names of the processes that are not language tools, without looking below a language tool. `caffeinate`
    (= claude runs it while it answers) and every command claude started are among them."""
    found: list[str] = []
    for node in nodes:
        if LANGUAGE_TOOLS.intersection(node.names):
            continue
        found.append(node.names[0] if node.names else "?")
        found.extend(foreign_processes(node.children))
    return tuple(found)


@dataclass(frozen=True)
class SleepFacts:
    """What was read about one tab. `None` = not read.

    turn_open:         claude is answering, or a message of the operator waits in its queue (= the last hook is not
                       a `Stop`, or a `UserPromptSubmit` came after it)
    quiet_minutes:     minutes since the newest row time of the conversation record or of a record of its sub-agents
    rollover_idle_pct: the agent's `rollover.idle.context_pct`, None when the agent has none (= the condition is off)
    """
    claude_running: bool | None = None
    starting: bool | None = None
    turn_open: bool | None = None
    record_found: bool | None = None
    quiet_minutes: float | None = None
    context_pct: float | None = None
    rollover_idle_pct: float | None = None
    foreign_processes: tuple[str, ...] | None = None
    record: RecordFacts | None = None
    on_voice_call: bool | None = None
    rolling_over: bool | None = None


def judge(facts: SleepFacts, minutes: float, by_hand: bool = False, stopped_by_limit: bool = False) -> tuple[str, ...]:
    """The conditions of `facts` that are not met for a tab that sleeps after `minutes` of quiet, or, `by_hand`, for a
    tab its parent puts to sleep now (= without `NOT_ASKED_BY_HAND`). `stopped_by_limit` is for a tab whose turn a
    usage limit stopped, which is interrupted at that stop (= without `LEFT_BY_A_LIMIT_STOP`). Empty = it may sleep."""
    left = (NOT_ASKED_BY_HAND if by_hand else frozenset()) | (LEFT_BY_A_LIMIT_STOP if stopped_by_limit else frozenset())
    return tuple(reason for reason in _unmet(facts, minutes) if reason not in left)


def _unmet(facts: SleepFacts, minutes: float) -> tuple[str, ...]:
    """Every condition of `facts` that is not met for a sleep after `minutes` of quiet."""
    reasons: list[str] = []
    if facts.claude_running is False:
        reasons.append(CLAUDE_NOT_RUNNING)
    if facts.starting:
        reasons.append(STARTING)
    if facts.turn_open:
        reasons.append(TURN_OPEN)
    if facts.record_found is False:
        reasons.append(NO_RECORD)
    elif facts.quiet_minutes is not None and facts.quiet_minutes < minutes:
        reasons.append(NOT_QUIET)
    if (facts.context_pct is not None and facts.rollover_idle_pct is not None
            and facts.context_pct >= facts.rollover_idle_pct):
        reasons.append(CONTEXT_AT_ROLLOVER_LINE)
    if facts.foreign_processes:
        reasons.append(PROCESSES_RUNNING)
    if facts.record is not None:
        if facts.record.wakeup_pending:
            reasons.append(WAKEUP_SCHEDULED)
        if facts.record.cron_open > 0:
            reasons.append(CRON_SCHEDULED)
        if facts.record.awaiting_tool_result:
            reasons.append(AWAITING_TOOL_RESULT)
    if facts.on_voice_call:
        reasons.append(VOICE_CALL)
    if facts.rolling_over:
        reasons.append(ROLLING_OVER)
    return tuple(reasons)
