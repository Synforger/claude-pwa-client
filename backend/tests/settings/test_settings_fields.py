"""Which fields of `config.json` the settings screen may change and to what (`settings_fields.py`). Pure: no file."""
from __future__ import annotations

import copy

import pytest

from backend.settings.settings_fields import Rejected, apply_update
from backend.tests.settings.conftest import SETTINGS


def apply(update):
    return apply_update(copy.deepcopy(SETTINGS), update)


@pytest.mark.parametrize("update, path, value", [
    ({"accounts": {"work": {"fallback": {"at_pct": 90}}}}, ("accounts", "work", "fallback", "at_pct"), 90),
    ({"accounts": {"work": {"fallback": {"seven_day_at_pct": {"tue": 50}}}}},
     ("accounts", "work", "fallback", "seven_day_at_pct", "tue"), 50),
    ({"accounts": {"personal": {"hold": {"seven_day_at_pct": {"sun": 80}}}}},
     ("accounts", "personal", "hold", "seven_day_at_pct", "sun"), 80),
    ({"accounts": {"work": {"fallback": {"ahead_pct": 5}}}}, ("accounts", "work", "fallback", "ahead_pct"), 5),
    ({"accounts": {"work": {"fallback": {"ahead_pct": 0}}}}, ("accounts", "work", "fallback", "ahead_pct"), 0),
    ({"accounts": {"work": {"fallback": {"ahead_pct": 50}}}}, ("accounts", "work", "fallback", "ahead_pct"), 50),
    ({"accounts": {"personal": {"hold": {"five_hour_at_pct": 95}}}},
     ("accounts", "personal", "hold", "five_hour_at_pct"), 95),
    ({"agents": {"agent_a": {"sleep": {"minutes": 30}}}}, ("agents", "agent_a", "sleep", "minutes"), 30),
    ({"agents": {"agent_b": {"sleep": {"minutes": 15}}}}, ("agents", "agent_b", "sleep", "minutes"), 15),
    ({"agents": {"agent_a": {"rollover": {"working": {"context_pct": 55}}}}},
     ("agents", "agent_a", "rollover", "working", "context_pct"), 55),
    ({"agents": {"agent_a": {"rollover": {"idle": {"context_pct": 35.5, "minutes": 45}}}}},
     ("agents", "agent_a", "rollover", "idle", "minutes"), 45),
    ({"child_sessions_max": 0}, ("child_sessions_max",), 0),
    ({"notification_title": "お知らせ"}, ("notification_title",), "お知らせ"),
])
def test_an_allowed_field_is_set_and_named_in_the_answer(update, path, value):
    updated, changed = apply(update)
    node = updated
    for key in path:
        node = node[key]
    assert node == value and changed and all(name.split(".")[0] == path[0] for name in changed)


def test_a_field_that_was_not_named_keeps_its_value_and_its_place():
    updated, _ = apply({"accounts": {"personal": {"hold": {"seven_day_at_pct": {"mon": 60}}}}})
    assert list(updated) == list(SETTINGS) and list(updated["accounts"]) == list(SETTINGS["accounts"])
    assert updated["accounts"]["work"] == SETTINGS["accounts"]["work"] and updated["agents"] == SETTINGS["agents"]
    assert updated["accounts"]["personal"]["hold"]["seven_day_at_pct"] == {"mon": 60, "sat": 100}


def test_what_was_given_is_not_changed():
    given = copy.deepcopy(SETTINGS)
    apply_update(given, {"child_sessions_max": 2})
    assert given == SETTINGS


def test_a_hold_is_made_on_an_account_that_has_none():
    settings = copy.deepcopy(SETTINGS)
    del settings["accounts"]["personal"]["hold"]
    updated, _ = apply_update(settings, {"accounts": {"personal": {"hold": {"seven_day_at_pct": {"fri": 90}}}}})
    assert updated["accounts"]["personal"]["hold"] == {"seven_day_at_pct": {"fri": 90}}


@pytest.mark.parametrize("update, gone", [
    ({"accounts": {"personal": {"hold": {"seven_day_at_pct": {"mon": None}}}}},
     lambda s: "mon" in s["accounts"]["personal"]["hold"]["seven_day_at_pct"]),
    ({"accounts": {"work": {"fallback": {"seven_day_at_pct": {"mon": None}}}}},
     lambda s: "mon" in s["accounts"]["work"]["fallback"]["seven_day_at_pct"]),
    ({"accounts": {"work": {"fallback": {"ahead_pct": None}}}}, lambda s: "ahead_pct" in s["accounts"]["work"]["fallback"]),
    ({"agents": {"agent_a": {"sleep": {"minutes": None}}}}, lambda s: "minutes" in s["agents"]["agent_a"]["sleep"]),
    ({"child_sessions_max": None}, lambda s: "child_sessions_max" in s),
    ({"notification_title": None}, lambda s: "notification_title" in s),
])
def test_null_removes_the_field(update, gone):
    updated, _ = apply(update)
    assert not gone(updated)


@pytest.mark.parametrize("update", [
    {"claude_path": "/bin/sh"},
    {"accounts": {"work": {"env": {"CLAUDE_CONFIG_DIR": "/x"}}}},
    {"accounts": {"work": {"fallback": {"to": "personal"}}}},
    {"accounts": {"work": {"display_name": "W"}}},
    {"accounts": {"personal": {"hold": {"seven_day_at_pct": {"funday": 50}}}}},
    {"agents": {"agent_a": {"cwd": "/elsewhere"}}},
    {"agents": {"agent_a": {"notification_title": "x"}}},
    {"agents": {"agent_a": {"rollover": {"idle": {"other": 1}}}}},
    {"vapid_sub": "mailto:a@b.c"},
])
def test_a_field_outside_the_list_is_refused_and_named(update):
    with pytest.raises(Rejected) as refused:
        apply(update)
    assert "cannot be changed here" in refused.value.reasons[0]


def test_every_refused_field_is_named_not_only_the_first():
    with pytest.raises(Rejected) as refused:
        apply({"claude_path": "x", "child_sessions_max": 3, "agents": {"agent_a": {"cwd": "/y"}}})
    assert len(refused.value.reasons) == 2 and "claude_path" in refused.value.reasons[0]


@pytest.mark.parametrize("update", [
    {"accounts": {"work": {"fallback": {"at_pct": 0}}}},
    {"accounts": {"work": {"fallback": {"at_pct": 101}}}},
    {"accounts": {"work": {"fallback": {"at_pct": "90"}}}},
    {"accounts": {"work": {"fallback": {"at_pct": 90.5}}}},
    {"accounts": {"work": {"fallback": {"at_pct": True}}}},
    {"accounts": {"work": {"fallback": {"at_pct": None}}}},
    {"accounts": {"personal": {"hold": {"seven_day_at_pct": {"mon": 0}}}}},
    {"accounts": {"personal": {"hold": {"seven_day_at_pct": {"mon": [70]}}}}},
    {"accounts": {"work": {"fallback": {"ahead_pct": -1}}}},
    {"accounts": {"work": {"fallback": {"ahead_pct": 51}}}},
    {"accounts": {"work": {"fallback": {"ahead_pct": 2.5}}}},
    {"accounts": {"work": {"fallback": {"ahead_pct": "5"}}}},
    {"accounts": {"work": {"fallback": {"ahead_pct": True}}}},
    {"accounts": {"personal": {"hold": {"five_hour_at_pct": 0}}}},
    {"accounts": {"personal": {"hold": {"five_hour_at_pct": 101}}}},
    {"accounts": {"personal": {"hold": {"five_hour_at_pct": 95.5}}}},
    {"accounts": {"personal": {"hold": {"five_hour_at_pct": "95"}}}},
    {"agents": {"agent_a": {"sleep": {"minutes": 0}}}},
    {"agents": {"agent_a": {"sleep": {"minutes": 1.5}}}},
    {"agents": {"agent_a": {"rollover": {"working": {"context_pct": 0}}}}},
    {"agents": {"agent_a": {"rollover": {"working": {"context_pct": 101}}}}},
    {"agents": {"agent_a": {"rollover": {"idle": {"minutes": 0}}}}},
    {"agents": {"agent_a": {"rollover": {"idle": {"minutes": "50"}}}}},
    {"child_sessions_max": -1},
    {"child_sessions_max": 2.5},
    {"child_sessions_max": False},
    {"notification_title": ""},
    {"notification_title": "  "},
    {"notification_title": 7},
])
def test_a_value_the_readers_would_not_use_is_refused(update):
    with pytest.raises(Rejected) as refused:
        apply(update)
    assert "must be" in refused.value.reasons[0] or "cannot be removed" in refused.value.reasons[0]


@pytest.mark.parametrize("update", [None, [], "x", {}, 5])
def test_an_update_that_names_nothing_is_refused(update):
    with pytest.raises(Rejected):
        apply(update)


def test_an_account_or_an_agent_that_is_not_in_the_settings_is_refused():
    with pytest.raises(Rejected) as refused:
        apply({"accounts": {"ghost": {"hold": {"seven_day_at_pct": {"mon": 50}}}}, "agents": {"ghost": {"sleep": {"minutes": 5}}}})
    assert len(refused.value.reasons) == 2 and "no account 'ghost'" in refused.value.reasons[0]


def test_the_fallback_line_of_an_account_without_a_fallback_is_refused():
    with pytest.raises(Rejected) as refused:
        apply({"accounts": {"personal": {"fallback": {"at_pct": 80}}}})
    assert "has no `fallback`" in refused.value.reasons[0]


def test_a_hold_cannot_be_given_to_an_account_that_moves_its_tabs_away():
    with pytest.raises(Rejected) as refused:
        apply({"accounts": {"work": {"hold": {"seven_day_at_pct": {"mon": 50}}}}})
    assert "accounts.work.hold is ignored" in refused.value.reasons[0] and "has a `fallback`" in refused.value.reasons[0]


def test_a_problem_that_was_there_already_does_not_stop_another_field_from_changing():
    settings = copy.deepcopy(SETTINGS)
    settings["accounts"]["personal"]["hold"] = "broken"          # an unusable hold, as a person may have left it
    updated, _ = apply_update(settings, {"accounts": {"work": {"fallback": {"at_pct": 80}}}})
    assert updated["accounts"]["work"]["fallback"]["at_pct"] == 80


def test_nothing_is_applied_when_one_field_is_refused():
    with pytest.raises(Rejected):
        apply({"child_sessions_max": 3, "agents": {"agent_a": {"sleep": {"minutes": 0}}}})


def test_the_line_of_the_5_hours_of_a_hold_is_removed_with_null_and_the_days_stay():
    settings = copy.deepcopy(SETTINGS)
    settings["accounts"]["personal"]["hold"]["five_hour_at_pct"] = 95
    updated, _ = apply_update(settings, {"accounts": {"personal": {"hold": {"five_hour_at_pct": None}}}})
    assert updated["accounts"]["personal"]["hold"] == {"seven_day_at_pct": {"mon": 70, "sat": 100}}


def test_a_line_of_the_5_hours_makes_a_hold_on_an_account_that_has_none():
    settings = copy.deepcopy(SETTINGS)
    del settings["accounts"]["personal"]["hold"]
    updated, changed = apply_update(settings, {"accounts": {"personal": {"hold": {"five_hour_at_pct": 90}}}})
    assert updated["accounts"]["personal"]["hold"] == {"five_hour_at_pct": 90}
    assert changed == ["accounts.personal.hold.five_hour_at_pct"]


def test_a_hold_whose_only_line_is_taken_away_is_refused_since_it_would_have_no_line_at_all():
    settings = copy.deepcopy(SETTINGS)
    settings["accounts"]["personal"]["hold"] = {"five_hour_at_pct": 95}
    with pytest.raises(Rejected) as refused:
        apply_update(settings, {"accounts": {"personal": {"hold": {"five_hour_at_pct": None}}}})
    assert "names neither" in refused.value.reasons[0]


def test_a_line_of_the_5_hours_cannot_be_given_to_an_account_that_moves_its_tabs_away():
    with pytest.raises(Rejected) as refused:
        apply({"accounts": {"work": {"hold": {"five_hour_at_pct": 90}}}})
    assert "has a `fallback`" in refused.value.reasons[0]


def test_the_width_ahead_of_the_line_of_an_account_without_a_fallback_is_refused():
    with pytest.raises(Rejected) as refused:
        apply({"accounts": {"personal": {"fallback": {"ahead_pct": 5}}}})
    assert "has no `fallback`" in refused.value.reasons[0]
