"""Which tool call of the conversation record a permission window belongs to. Pure: it reads no file and no state.

A window is asked for by a `PermissionRequest` hook (the tool and its input, no id) while the record holds the call as a
`tool_use` row (an id, the input the model wrote) that has no result yet. The table is the calls without a result;
`select` picks the one a hook is about: the call with the same tool and the same input, else, when a guard rewrote the
input (the hook and the window carry the rewritten one, the record the original), the oldest call of the same tool.

Used by `window_state.py`.
"""
from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field

from backend.permission_window.window_judgement import Kind

# The attachment row that ends a call a hook decided (`toolUseID` is the call).
DECISION_ATTACHMENT = "hook_permission_decision"
# The tools whose window is a question to answer or a plan to approve; every other call is an approval.
QUESTION_TOOL = "AskUserQuestion"
PLAN_TOOL = "ExitPlanMode"


@dataclass(frozen=True)
class RecordedCall:
    """One `tool_use` of the record: its id, the tool and the input the model wrote."""
    tool_use_id: str
    tool_name: str
    tool_input: dict


@dataclass
class CallTable:
    """The calls of the current turn: those without a result (`open`, oldest first) and those with one (`resolved`)."""
    open: dict[str, RecordedCall] = field(default_factory=dict)
    resolved: dict[str, RecordedCall] = field(default_factory=dict)

    def clear(self) -> None:
        self.open.clear()
        self.resolved.clear()


@dataclass(frozen=True)
class RowEffect:
    """What one record row did to the table: the calls it added and the ids it resolved."""
    added: tuple[RecordedCall, ...] = ()
    resolved_ids: tuple[str, ...] = ()
    new_turn: bool = False


def effect_of_row(row: dict) -> RowEffect:
    """What a record row does to the table: an assistant row adds its `tool_use` blocks, a `tool_result` or a
    `hook_permission_decision` attachment resolves its call, and a row of the operator's own words starts a new turn
    (= whatever was left without a result belongs to the turn before)."""
    row_type = row.get("type")
    if row_type == "assistant":
        blocks = (row.get("message") or {}).get("content")
        calls = tuple(RecordedCall(block["id"], block.get("name") or "", block.get("input") or {})
                      for block in blocks if isinstance(block, dict) and block.get("type") == "tool_use"
                      and isinstance(block.get("id"), str)) if isinstance(blocks, list) else ()
        return RowEffect(added=calls)
    if row_type == "user":
        content = (row.get("message") or {}).get("content")
        if isinstance(content, list):
            ids = tuple(block["tool_use_id"] for block in content if isinstance(block, dict)
                        and block.get("type") == "tool_result" and isinstance(block.get("tool_use_id"), str))
            if ids:
                return RowEffect(resolved_ids=ids)
        return RowEffect(new_turn=True)
    if row_type == "attachment":
        attachment = row.get("attachment") or {}
        if attachment.get("type") == DECISION_ATTACHMENT and isinstance(attachment.get("toolUseID"), str):
            return RowEffect(resolved_ids=(attachment["toolUseID"],))
    return RowEffect()


def apply_effect(table: CallTable, effect: RowEffect) -> None:
    """Fold a row's effect into the table."""
    if effect.new_turn:
        table.clear()
    for call in effect.added:
        table.open[call.tool_use_id] = call
    for tool_use_id in effect.resolved_ids:
        call = table.open.pop(tool_use_id, None)
        if call is not None:
            table.resolved[tool_use_id] = call


def select(calls: dict[str, RecordedCall], tool_name: str, tool_input: dict, taken: frozenset[str]) -> RecordedCall | None:
    """The call of `calls` (oldest first) a hook for `tool_name` with `tool_input` is about, leaving out the ids in
    `taken` (= calls an earlier window already belongs to): the first with the same tool and the same input, else the
    first of the same tool. None when there is none."""
    same_tool = [call for call in calls.values() if call.tool_name == tool_name and call.tool_use_id not in taken]
    for call in same_tool:
        if call.tool_input == tool_input:
            return call
    return same_tool[0] if same_tool else None


def oldest_kind(calls: dict[str, RecordedCall]) -> Kind:
    """What the window on the screen is, by the oldest call (the first of `calls`) that has no result: a question, a plan,
    an approval; `Kind.NONE` when no call is waiting."""
    for call in calls.values():
        if call.tool_name == QUESTION_TOOL:
            return Kind.QUESTION
        if call.tool_name == PLAN_TOOL:
            return Kind.PLAN
        return Kind.APPROVAL
    return Kind.NONE


def table_of_turn(rows: Iterable[dict]) -> CallTable:
    """The table the rows of a turn leave, `rows` oldest first."""
    table = CallTable()
    for row in rows:
        apply_effect(table, effect_of_row(row))
    return table
