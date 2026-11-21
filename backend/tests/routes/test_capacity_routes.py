"""`GET /capacity` (= `backend/routes/capacity.py`): its answer keeps the contract, and only this machine may ask."""
from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend._generated import http_endpoints as declared
from backend.capacity.capacity_sensors import MemoryNow, TabFacts


def _client(monkeypatch, address: str | None = None) -> TestClient:
    import backend.routes.capacity as capacity_routes  # noqa: PLC0415
    sensors = capacity_routes.capacity_sensors
    monkeypatch.setattr(sensors, "read_tabs", lambda: [
        TabFacts(id="ses_p", child=False, parent_id=None, asleep=False, account="work", has_claude=True, claude_mb=260.0),
        TabFacts(id="ses_k", child=True, parent_id="ses_p", asleep=False, account="work", has_claude=True, claude_mb=240.0)])
    monkeypatch.setattr(sensors, "read_memory_now", lambda: MemoryNow(total_mb=32768.0, available_mb=5000.0, level=1,
                                                                      swap_used_mb=0.0))
    monkeypatch.setattr(sensors, "read_usage", lambda: {"work": None})
    app = FastAPI()
    app.include_router(capacity_routes.router)
    return TestClient(app, client=(address, 50000)) if address else TestClient(app)


def test_the_answer_keeps_the_declared_shape_and_counts_the_callers_children(monkeypatch):
    response = _client(monkeypatch).get("/capacity", params={"session": "ses_p"})
    assert response.status_code == 200
    answer = declared.GetCapacityResponse.model_validate(response.json())
    assert answer.children_of_caller == 1 and answer.claudes_fitting_available == 20


def test_only_a_program_on_this_machine_may_ask(monkeypatch):
    response = _client(monkeypatch, "100.64.0.7").get("/capacity")
    assert response.status_code == 403 and response.json()["detail"]["code"] == "capacity_local_only"
