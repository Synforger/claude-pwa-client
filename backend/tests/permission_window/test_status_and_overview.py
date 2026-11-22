"""The rows of a conversation record tie a permission window to its call and close it (`jsonl/session_status.py`), and the
window reaches the screen through the same status as a plan approval (`agent_status.pending_permission`, the overview)."""
from __future__ import annotations

from backend._common.state import agent_status
from backend.jsonl import session_status
from backend.permission_window import window_state
from backend.tests.permission_window.conftest import SID, call_row, decision_row, result_row


def test_the_rows_of_the_record_tie_the_window_to_its_call_and_the_result_closes_it(tab):
    session_status.mutate_agent_status(SID, call_row("toolu_1", "Bash", {"command": "ls"}))
    window_state.open_window(SID, "Bash", {"command": "ls"}, "p1", now=1.0)
    assert agent_status[SID]["pending_permission"]["tool_use_id"] == "toolu_1"
    session_status.mutate_agent_status(SID, decision_row("toolu_1"))
    assert agent_status[SID]["pending_permission"] is None


def test_a_row_of_a_sub_agent_does_not_tie_a_window(tab):
    row = {**call_row("toolu_s", "Bash", {"command": "ls"}), "isSidechain": True}
    session_status.mutate_agent_status(SID, row)
    window = window_state.open_window(SID, "Bash", {"command": "ls"}, "p1", now=1.0)
    assert window.tool_use_id is None


def test_the_answer_to_a_plan_approval_tells_the_texts_that_waited_for_it(tab):
    told = []
    window_state.add_close_listener(told.append)
    tab["pending_plan"] = {"tool_use_id": "toolu_p", "plan": "x", "choices": []}
    session_status.mutate_agent_status(SID, result_row("toolu_p"))
    assert tab["pending_plan"] is None and told == [SID]


def test_a_new_status_has_no_window():
    from backend._common.state import AgentStatus
    assert AgentStatus().to_dict()["pending_permission"] is None


def test_the_status_of_every_tab_carries_the_window_to_the_screen(tab, monkeypatch):
    """`/sessions/status/stream` names each field it sends: the screen gets the window only if it is named there."""
    from backend._common import state as state_mod
    from backend.routes import overview
    monkeypatch.setitem(state_mod.sessions_meta, SID, state_mod.SessionDef(id=SID, agent_id="a", title="t", created_at=0))
    for key, value in {"pending_plan": None, "pending_permission": None, "model": "", "ctx_pct": 0, "plan_mode": False,
                       "current_tool": None, "todos": None, "subagent": None}.items():
        tab.setdefault(key, value)
    assert overview._build_all_status()[SID]["pending_permission"] is None
    session_status.mutate_agent_status(SID, call_row("toolu_1", "Bash", {"command": "ls"}))
    window_state.open_window(SID, "Bash", {"command": "ls"}, "p1", now=7.0)
    shown = overview._build_all_status()[SID]["pending_permission"]
    assert (shown["number"], shown["tool_use_id"], shown["input"], shown["opened_at"]) == (
        1, "toolu_1", {"command": "ls"}, 7.0)
