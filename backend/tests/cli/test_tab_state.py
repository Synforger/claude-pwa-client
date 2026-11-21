"""`tabs list` の状態の語の決め方 (= この機械のタブと別の機械のタブが同じ語を出す)。"""
from __future__ import annotations

import pytest

from backend.cli.peer_tab_lines import peer_tab_lines
from backend.cli.tab_state import peer_tab_state, state_word


@pytest.mark.parametrize(("status", "asleep", "reachable", "word"), [
    ("busy", False, True, "busy"),
    ("idle", True, True, "idle"),          # claude が動いていれば、 眠りの印が残っていてもその状態
    (None, True, True, "眠り"),
    (None, True, False, "眠り"),
    (None, False, True, "未起動"),
    (None, False, False, "起こせない"),
])
def test_a_tab_has_one_word_from_what_is_known_of_it(status, asleep, reachable, word):
    assert state_word(status, asleep=asleep, reachable=reachable) == word


def test_a_tab_of_another_machine_gets_the_same_words():
    assert peer_tab_state({"id": "a", "running": True, "status": "busy", "asleep": False}) == "busy"
    assert peer_tab_state({"id": "b", "running": True, "status": None, "asleep": True}) == "眠り"
    assert peer_tab_state({"id": "c", "running": True, "status": None, "asleep": False}) == "未起動"
    assert peer_tab_state({"id": "d", "running": False, "status": None, "asleep": False}) == "起こせない"


def test_a_row_from_a_backend_that_gives_no_state_is_not_taken_for_a_sleeping_or_a_missing_tab():
    assert peer_tab_state({"id": "e", "running": True}) == "?"
    assert peer_tab_state({"id": "f", "running": False}) == "起こせない"


def test_the_lines_keep_the_machine_and_the_id_first_and_list_every_tab():
    lines = peer_tab_lines([
        {"name": "company", "error": None, "tabs": [
            {"id": "ses_x", "title": "番人", "running": True, "status": None, "asleep": True},
            {"id": "ses_y", "title": "work", "running": True, "status": "idle", "asleep": False},
            {"id": "ses_z", "title": "", "running": False, "status": None, "asleep": False}]},
        {"name": "lab", "tabs": None, "error": "unreachable"},
    ])
    assert lines == [
        "company:ses_x  別の機械  眠り  番人",
        "company:ses_y  別の機械  idle  work",
        "company:ses_z  別の機械  起こせない",
        "lab:  別の機械  一覧を取れません (unreachable)",
    ]
