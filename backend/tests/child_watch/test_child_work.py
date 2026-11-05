"""A message a parent delivers to its child sets the child's memo back to working (`child_watch/child_work.py`)."""
from __future__ import annotations

import pytest

from backend._common.state import register_session
from backend.child_watch.child_memo import WORKING, memo_state
from backend.child_watch.child_work import hand_work, memo_of


@pytest.fixture
def tabs(isolated_state, agent_folder):
    parent = register_session("agent_a", title="Parent")
    child = register_session("agent_a", title="Port the module", child=True, parent_id=parent.id)
    other = register_session("agent_a", title="Other")
    memo = agent_folder / "pages" / child.id / "memo.md"
    memo.parent.mkdir(parents=True)
    memo.write_text(f"# {child.title}\n\n- 親のタブ: {parent.id}\n- 状態: 完了\n", encoding="utf-8")
    return parent, child, other, memo


def test_a_message_from_the_parent_to_a_child_that_reported_sets_its_memo_back_to_working(tabs):
    parent, child, _other, memo = tabs
    assert memo_of(child) == memo
    assert hand_work(parent.id, child.id) is True
    assert memo_state(memo) == WORKING


@pytest.mark.parametrize("state", ["詰まり", "完了"])
def test_a_report_of_either_kind_is_set_back(tabs, state):
    parent, child, _other, memo = tabs
    memo.write_text(f"# T\n\n- 状態: {state}\n", encoding="utf-8")
    assert hand_work(parent.id, child.id) is True and memo_state(memo) == WORKING


def test_a_child_already_working_is_left_as_it_is(tabs):
    parent, child, _other, memo = tabs
    memo.write_text("# T\n\n- 状態: 作業中\n", encoding="utf-8")
    before = memo.stat().st_mtime_ns
    assert hand_work(parent.id, child.id) is False and memo.stat().st_mtime_ns == before


def test_a_message_from_another_tab_does_not_change_the_memo(tabs):
    _parent, child, other, memo = tabs
    assert hand_work(other.id, child.id) is False and memo_state(memo) == "完了"


def test_a_tab_that_is_not_a_child_or_has_no_memo_is_left_alone(tabs, agent_folder):
    parent, child, other, memo = tabs
    assert hand_work(child.id, parent.id) is False
    assert hand_work(parent.id, other.id) is False
    memo.unlink()
    assert hand_work(parent.id, child.id) is False and not memo.exists()
