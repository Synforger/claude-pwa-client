"""apply_pending_question / apply_immediate_stop の unit test (= F-12 / F-69)。

hook と JSONL tail が同じ helper を呼んで merge 収束することを保証する。 hook 側の
mutate 撤廃 commit と本 test がペアで「2 経路 race ゼロ」 を担保する。
"""
import pytest

import backend.state as state_mod
from backend.jsonl.session_status import apply_immediate_stop, apply_pending_question


@pytest.fixture
def sid(isolated_state):
    """単発 session を用意する。 isolated_state が global dict を snapshot/restore する
    ので、 test 終了時に state は完全復元される。"""
    s = "ses_test"
    isolated_state.agent_status[s] = {
        "current_tool": None, "subagent": None, "pending_question": None,
    }
    isolated_state.stream_states[s] = state_mod.StreamState(agent_id="a")
    return s


# --- apply_pending_question (= F-69 merge) -------------------------------

def test_apply_pq_new_sets_from_none(sid):
    qs = [{"question": "go?", "options": ["y", "n"]}]
    assert apply_pending_question(sid, qs, tool_use_id="t1") is True
    pq = state_mod.agent_status[sid]["pending_question"]
    assert pq == {"tool_use_id": "t1", "questions": qs}


def test_apply_pq_hook_first_then_jsonl_fills_id(sid):
    """hook が tool_use_id=None で立てた後、 JSONL tail が同 questions + tool_use_id
    で来て id 補完される (= 旧来の正常経路、 仕様維持)。"""
    qs = [{"question": "go?", "options": ["y", "n"]}]
    apply_pending_question(sid, qs, tool_use_id=None)
    assert state_mod.agent_status[sid]["pending_question"]["tool_use_id"] is None
    # JSONL tail で id 来る → 補完されて True
    assert apply_pending_question(sid, qs, tool_use_id="t1") is True
    assert state_mod.agent_status[sid]["pending_question"]["tool_use_id"] == "t1"


def test_apply_pq_hook_duplicate_does_not_clear_known_id(sid):
    """JSONL tail で id 補完済の後に hook が None で再到着 (= 重複) しても、 既知 id を
    None で上書きしない (= 旧 race 真因の修正)。"""
    qs = [{"question": "go?"}]
    apply_pending_question(sid, qs, tool_use_id="t1")
    # hook 重複到着 (= tool_use_id=None)
    assert apply_pending_question(sid, qs, tool_use_id=None) is False
    assert state_mod.agent_status[sid]["pending_question"]["tool_use_id"] == "t1"


def test_apply_pq_different_questions_replaces(sid):
    """questions の中身が変わる = 別質問への切替なので新規 set (= id も差し替え)。"""
    qs1 = [{"question": "a?"}]
    qs2 = [{"question": "b?"}]
    apply_pending_question(sid, qs1, tool_use_id="t1")
    assert apply_pending_question(sid, qs2, tool_use_id="t2") is True
    pq = state_mod.agent_status[sid]["pending_question"]
    assert pq["questions"] == qs2
    assert pq["tool_use_id"] == "t2"


def test_apply_pq_same_state_returns_false(sid):
    """同じ questions + 同じ id で再呼出は no-op (= idempotent)。"""
    qs = [{"question": "go?"}]
    apply_pending_question(sid, qs, tool_use_id="t1")
    assert apply_pending_question(sid, qs, tool_use_id="t1") is False


def test_apply_pq_empty_questions_noop(sid):
    """questions が空 → 何もしない (= 不正 hook 入力で state を壊さない)。"""
    assert apply_pending_question(sid, [], tool_use_id="t1") is False
    assert state_mod.agent_status[sid]["pending_question"] is None


def test_apply_pq_unknown_sid_noop():
    """登録外 sid は黙って無視。"""
    assert apply_pending_question("__no_such_sid__", [{"question": "x"}]) is False


def test_apply_pq_notifies_overview(sid):
    """変化発生時に sessions_overview と status_event が叩かれる。"""
    ev = state_mod.sessions_overview.subscribe()
    ev.clear()
    state_mod.stream_states[sid].status_event.clear()
    qs = [{"question": "go?"}]
    apply_pending_question(sid, qs, tool_use_id="t1")
    assert ev.is_set() is True
    assert state_mod.stream_states[sid].status_event.is_set() is True


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
