"""`backend/capacity/capacity_view.py`: the plain numbers of `GET /capacity`, built from what was read."""
from __future__ import annotations

from backend.capacity.capacity_sensors import MemoryNow, TabFacts
from backend.capacity.capacity_view import build_view

MEMORY = MemoryNow(total_mb=32768.0, available_mb=5000.0, level=1, swap_used_mb=2048.0)


def tab(tab_id: str, *, claude_mb: float | None = None, asleep: bool = False, child: bool = False,
        parent_id: str | None = None, account: str = "work") -> TabFacts:
    return TabFacts(id=tab_id, child=child, parent_id=parent_id, asleep=asleep, account=account,
                    has_claude=claude_mb is not None, claude_mb=claude_mb)


def view(tabs, *, caller=None, child_sessions_max=None, usage=None):
    return build_view(machine="company", child_sessions_max=child_sessions_max, caller=caller, tabs=tabs,
                      memory=MEMORY, usage={"work": None} if usage is None else usage)


def test_tabs_are_counted_by_whether_a_claude_runs_or_sleeps():
    tabs = [tab("a", claude_mb=200.0), tab("b", claude_mb=300.0, child=True, parent_id="a"),
            tab("c", asleep=True), tab("d")]
    assert view(tabs)["tabs"] == {"total": 4, "with_claude": 2, "asleep": 1, "without_claude": 1, "children": 1}


def test_the_footprints_and_how_many_more_fit_are_plain_numbers():
    answer = view([tab("a", claude_mb=200.0), tab("b", claude_mb=300.0), tab("c", claude_mb=250.0)])
    assert answer["claude_mb"] == {"count": 3, "median": 250.0, "min": 200.0, "max": 300.0, "total": 750.0}
    assert answer["claudes_fitting_available"] == 20  # 5000 MB // 250 MB
    assert answer["memory"] == {"total_mb": 32768.0, "available_mb": 5000.0, "pressure_level": 1, "swap_used_mb": 2048.0}


def test_with_no_running_claude_nothing_is_guessed():
    answer = view([tab("a", asleep=True)])
    assert answer["claude_mb"] is None and answer["claudes_fitting_available"] is None


def test_the_child_limit_is_given_as_written_and_the_callers_children_are_counted():
    tabs = [tab("p", claude_mb=200.0), tab("k1", child=True, parent_id="p"), tab("k2", child=True, parent_id="p"),
            tab("f", parent_id="p"), tab("k3", child=True, parent_id="other")]
    assert view(tabs, caller="p")["children_of_caller"] == 2  # a fork of p is not its child
    assert view(tabs)["children_of_caller"] is None
    assert view(tabs)["child_sessions_max"] is None
    assert view(tabs, child_sessions_max=4)["child_sessions_max"] == 4


def test_each_account_has_its_usage_and_its_running_claudes():
    usage = {"work": {"five_hour_pct": 11, "five_hour_resets_at": 1, "seven_day_pct": 87, "seven_day_resets_at": 2},
             "personal": None}
    tabs = [tab("a", claude_mb=200.0), tab("b", claude_mb=200.0, account="personal"), tab("c", account="personal")]
    assert view(tabs, usage=usage)["accounts"] == [
        {"id": "work", "usage": usage["work"], "tabs_with_claude": 1},
        {"id": "personal", "usage": None, "tabs_with_claude": 1}]
