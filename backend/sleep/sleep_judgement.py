"""Whether a tab's claude may be put to sleep. Pure: it takes the facts the sensors read and answers with the
conditions that are not met; it reads no file, no process and no state.

A tab may sleep only when every condition holds. Each condition that fails is returned, so the log can say why a
quiet tab was left awake. The sensors read the cheap facts first and stop at the first condition that fails, so a
fact that was not read is `None` here and its condition is skipped; an answer with no failing condition is always
about facts that were all read.

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
    quiet_minutes:     minutes since the newest write to the conversation record or to a record of its sub-agents
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


def judge(facts: SleepFacts, minutes: float) -> tuple[str, ...]:
    """The conditions of `facts` that are not met for a tab that sleeps after `minutes` of quiet. Empty = it may sleep."""
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
