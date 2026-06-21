"""tasks 比較正規化の unit test (= backend-F-57)。

task_reminder snapshot を agent_status.tasks に差し替える経路で、 dict 全 field 比較
だと余計な field / 順序揺らぎで false positive を起こしていた。 表示 field のみ + sort
正規化での比較に切替えたことを担保する。
"""
from backend.jsonl.session_status import _tasks_signature, mutate_agent_status


def _t(id_, subject, status="pending", extra=None):
    base = {
        "id": id_, "subject": subject,
        "description": "", "activeForm": "", "status": status,
    }
    if extra:
        base.update(extra)
    return base


def test_signature_empty_inputs():
    assert _tasks_signature([]) == []
    assert _tasks_signature(None) == []  # type: ignore[arg-type]


def test_signature_extracts_display_fields_only():
    sig = _tasks_signature([_t("1", "Write tests", extra={"timestamp": 123, "internal": "x"})])
    assert sig == [("1", "Write tests", "", "", "pending")]


def test_signature_normalizes_order():
    """同じ task が順序違いで来ても signature は一致 (= 不要再描画を防ぐ)。"""
    a = [_t("1", "a"), _t("2", "b")]
    b = [_t("2", "b"), _t("1", "a")]
    assert _tasks_signature(a) == _tasks_signature(b)


def test_signature_detects_status_change():
    a = [_t("1", "a", status="pending")]
    b = [_t("1", "a", status="completed")]
    assert _tasks_signature(a) != _tasks_signature(b)


def test_signature_detects_id_change():
    a = [_t("1", "a")]
    b = [_t("2", "a")]
    assert _tasks_signature(a) != _tasks_signature(b)


def test_signature_ignores_extra_metadata():
    """timestamp / 内部メタが差分でも signature は同じ (= 過剰発火しない)。"""
    a = [_t("1", "a", extra={"timestamp": 100})]
    b = [_t("1", "a", extra={"timestamp": 200, "trace": "x"})]
    assert _tasks_signature(a) == _tasks_signature(b)


def test_signature_handles_non_dict_entries_safely():
    """型不正 entry は signature から弾く (= 例外を投げない)。"""
    sig = _tasks_signature([_t("1", "a"), None, "garbage", 42, _t("2", "b")])
    assert len(sig) == 2


def test_task_reminder_no_change_does_not_dirty_flag(isolated_state):
    """同じ task snapshot を 2 回流して、 1 回目だけ changed=True を返す
    (= task_reminder 再掲で frontend を毎ターン再描画させない)。"""
    state = isolated_state
    sid = "ses_tr"
    state.agent_status[sid] = {
        "tasks": [], "current_tool": None, "todos": None, "subagent": None,
        "pending_question": None, "pending_plan": None, "plan_mode": False,
        "model": "", "ctx_pct": 0, "ctx_window": 1_000_000,
        "pr_links": [], "mode": "", "permission_mode": "",
        "budget_used": None, "budget_total": None, "budget_remaining": None,
    }
    tasks_a = [_t("1", "Write tests"), _t("2", "Refactor")]
    tasks_b_reordered = [_t("2", "Refactor"), _t("1", "Write tests")]
    line_a = {"type": "attachment", "attachment": {"type": "task_reminder", "content": tasks_a}}
    line_b = {"type": "attachment", "attachment": {"type": "task_reminder", "content": tasks_b_reordered}}

    # 1 回目: 空 → tasks 入る = True
    assert mutate_agent_status(sid, line_a) is True
    # 2 回目: 順序違いだけ → signature 同じで changed=False (= 過剰発火しない)
    assert mutate_agent_status(sid, line_b) is False


def test_task_reminder_status_change_dirty_flag(isolated_state):
    """status だけ違えば changed=True (= 本質的変化は確実に拾う)。"""
    state = isolated_state
    sid = "ses_tr2"
    state.agent_status[sid] = {
        "tasks": [_t("1", "a", status="pending")],
        "current_tool": None, "todos": None, "subagent": None,
        "pending_question": None, "pending_plan": None, "plan_mode": False,
        "model": "", "ctx_pct": 0, "ctx_window": 1_000_000,
        "pr_links": [], "mode": "", "permission_mode": "",
        "budget_used": None, "budget_total": None, "budget_remaining": None,
    }
    line = {"type": "attachment", "attachment": {
        "type": "task_reminder", "content": [_t("1", "a", status="completed")]
    }}
    assert mutate_agent_status(sid, line) is True
