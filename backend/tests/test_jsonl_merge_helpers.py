"""apply_immediate_stop の unit test (= F-12)。

hook と JSONL tail が同じ helper を呼んで merge 収束することを保証する。
(旧 apply_pending_question 系 test は Phase 2 (= 2026-07-06) の配管退役で削除)
"""
import pytest

import backend.state as state_mod
from backend.jsonl.session_status import apply_immediate_stop


@pytest.fixture
def sid(isolated_state):
    """単発 session を用意する。 isolated_state が global dict を snapshot/restore する
    ので、 test 終了時に state は完全復元される。"""
    s = "ses_test"
    isolated_state.agent_status[s] = {
        "current_tool": None, "subagent": None,
    }
    isolated_state.stream_states[s] = state_mod.StreamState(agent_id="a")
    return s


# --- apply_immediate_stop (= F-12) ---------------------------------------

def test_apply_stop_clears_current_tool_and_subagent(sid):
    state_mod.agent_status[sid]["current_tool"] = {"name": "Task", "id": "t1"}
    state_mod.agent_status[sid]["subagent"] = {"last_tool": "Read"}
    assert apply_immediate_stop(sid) is True
    assert state_mod.agent_status[sid]["current_tool"] is None
    assert state_mod.agent_status[sid]["subagent"] is None


def test_apply_stop_idempotent(sid):
    # 既に両方 None なら no-op
    assert apply_immediate_stop(sid) is False


def test_apply_stop_unknown_sid_noop():
    assert apply_immediate_stop("__no_such_sid__") is False


def test_apply_stop_notifies_overview(sid):
    ev = state_mod.sessions_overview.subscribe()
    ev.clear()
    state_mod.stream_states[sid].status_event.clear()
    state_mod.agent_status[sid]["current_tool"] = {"name": "Bash", "id": "t1"}
    apply_immediate_stop(sid)
    assert ev.is_set() is True
    assert state_mod.stream_states[sid].status_event.is_set() is True


def test_apply_stop_partial_clears_only_changed_field(sid):
    """current_tool だけ非 None、 subagent は None → current_tool だけ落とす + True を返す。"""
    state_mod.agent_status[sid]["current_tool"] = {"name": "Bash", "id": "t"}
    state_mod.agent_status[sid]["subagent"] = None
    assert apply_immediate_stop(sid) is True
    assert state_mod.agent_status[sid]["current_tool"] is None
