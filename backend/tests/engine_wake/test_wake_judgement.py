"""Which engines are woken and put to rest, and what a look does with one (`backend/engine_wake/wake_judgement.py`)."""
from __future__ import annotations

import pytest

from backend.engine_wake.wake_judgement import LEAVE, STOP, WAKE, engine_services, next_step

URL = "http://127.0.0.1:10101"


def _agent(engine=URL, service=None, speaker=7) -> dict:
    voice = {"engine": engine, "speaker": speaker}
    if service is not None:
        voice["engine_service"] = service
    return {"voice": voice}


def test_only_the_agents_that_name_a_service_have_their_engine_handled():
    services, warnings = engine_services({"a": _agent(service={"label": "x.voice"}), "b": _agent("http://h:1"),
                                          "c": {"cwd": "/"}})
    assert list(services) == [URL] and warnings == []
    assert (services[URL].label, services[URL].idle_minutes, services[URL].speaker) == ("x.voice", 10.0, 7)


def test_agents_on_one_engine_share_it_with_the_first_label_and_the_longest_idle_time():
    services, warnings = engine_services({
        "a": _agent(URL + "/", {"label": "x.voice", "idle_minutes": 5}),
        "b": _agent(URL, {"label": "y.voice", "idle_minutes": 20}, speaker=9),
    })
    assert (services[URL].label, services[URL].idle_minutes, services[URL].speaker) == ("x.voice", 20.0, 7)
    assert len(warnings) == 1 and "y.voice" in warnings[0]


@pytest.mark.parametrize("service", [
    "x.voice", {"label": ""}, {"label": 3}, {"idle_minutes": 5}, {"label": "x", "idle_minutes": 0},
    {"label": "x", "idle_minutes": -1}, {"label": "x", "idle_minutes": True}, {"label": "x", "idle_minutes": "5"},
])
def test_a_service_written_wrongly_is_not_handled_and_is_warned_about(service):
    services, warnings = engine_services({"a": _agent(service=service)})
    assert services == {} and len(warnings) == 1


def test_an_agent_without_an_engine_url_is_warned_about():
    services, warnings = engine_services({"a": _agent(engine=None, service={"label": "x"})})
    assert services == {} and "voice.engine" in warnings[0]


def _step(**facts) -> str:
    base = {"voice_open": False, "answers": True, "busy": False, "waiting_to_retry": False, "idle_minutes": 10,
            "quiet_minutes": 0}
    return next_step(**{**base, **facts})


@pytest.mark.parametrize(("facts", "step"), [
    ({"voice_open": True, "answers": False}, WAKE),
    ({"voice_open": True, "answers": True}, LEAVE),
    ({"voice_open": True, "answers": False, "waiting_to_retry": True}, LEAVE),
    ({"answers": True, "quiet_minutes": 9.9}, LEAVE),
    ({"answers": True, "quiet_minutes": 10}, STOP),
    ({"answers": False, "quiet_minutes": 60}, LEAVE),
    ({"busy": True, "voice_open": True, "answers": False}, LEAVE),
    ({"busy": True, "quiet_minutes": 60}, LEAVE),
    ({"answers": True, "quiet_minutes": 60, "kept_alive": True}, LEAVE),
    ({"voice_open": True, "answers": False, "kept_alive": True}, WAKE),
])
def test_what_a_look_does(facts, step):
    assert _step(**facts) == step
