"""The state line of a child tab's memo is read the same way by the backend and by the `tabs` command
(`child_watch/child_memo.py`)."""
from __future__ import annotations

from backend.child_watch.child_memo import STATE_LINE, UNKNOWN, WORKING, memo_state


def test_the_state_is_the_text_after_the_label_of_the_line(tmp_path):
    memo = tmp_path / "memo.md"
    memo.write_text("# T\n\n- 親のタブ: ses_p\n- 状態: 作業中 \n- 階層: normal\n", encoding="utf-8")
    assert memo_state(memo) == WORKING


def test_a_memo_that_is_missing_unreadable_or_without_the_line_is_unknown(tmp_path):
    memo = tmp_path / "memo.md"
    assert memo_state(tmp_path / "none.md") == UNKNOWN and memo_state(None) == UNKNOWN
    memo.write_text("# T\n\nno state here\n", encoding="utf-8")
    assert memo_state(memo) == UNKNOWN
    memo.write_bytes(b"\xff\xfe- \x80")
    assert memo_state(memo) == UNKNOWN


def test_only_a_whole_line_counts(tmp_path):
    memo = tmp_path / "memo.md"
    memo.write_text("text - 状態: 完了\n", encoding="utf-8")
    assert memo_state(memo) == UNKNOWN and STATE_LINE.search("- 状態: 詰まり").group(1) == "詰まり"
