"""The child's lines stay readable by what reads envelopes line by line, and name the memo as the rest of the client
does."""
from __future__ import annotations

import pytest

from backend._common import child_role
from backend.child_watch.child_memo import WORKING


@pytest.mark.parametrize("write", [child_role.rollover_lines, child_role.opening_lines])
@pytest.mark.parametrize("parent", ["ses_p", None])
def test_only_the_child_s_own_keys_can_be_read_from_its_lines(write, parent):
    lines = write(parent)
    assert all("\n" not in line for line in lines)
    keys = [line.partition("=")[0] for line in lines if "=" in line]
    assert keys == (["child", "parent"] if parent else ["child"])
    assert "<child-start>" not in "".join(lines) and "</" not in "".join(lines)


@pytest.mark.parametrize("write", [child_role.rollover_lines, child_role.opening_lines])
def test_the_lines_point_at_the_memo_and_away_from_the_journal(write):
    prose = write("ses_p")[-1]
    assert child_role.HANDED in prose and child_role.CARRY in prose and "journal" in prose


def test_the_state_the_lines_name_is_the_memo_s_word_for_working():
    assert WORKING in child_role.rollover_lines("ses_p")[-1]


@pytest.mark.parametrize("parent, tabs, known", [("p", {"p": 1}, "p"), ("p", {}, None), (None, {"p": 1}, None)])
def test_a_parent_is_named_only_while_its_tab_exists(parent, tabs, known):
    assert child_role.known_parent(parent, tabs) == known
