"""The status every screen gets (`backend/routes/overview.py`): a usage that is not known is null. Run by pytest."""
from __future__ import annotations

import pytest

import backend._common.state as state_mod
import backend.routes.overview as overview


@pytest.mark.parametrize("rows", [
    pytest.param([], id="no-row"),
    pytest.param([{"account_id": "personal", "seven_day_pct": 7, "seven_day_resets_at": 2_000}], id="week-alone"),
])
def test_a_window_that_is_not_known_is_null_in_the_status(
        rows: list[dict], isolated_state, monkeypatch: pytest.MonkeyPatch) -> None:
    sid = "ses_usage"
    isolated_state.agent_status[sid] = state_mod._make_agent_status("agent_a")
    isolated_state.sessions_meta[sid] = state_mod.SessionDef(id=sid, agent_id="agent_a", title=sid, created_at=0)
    monkeypatch.setattr(overview, "read_all_rate_limits_tail", lambda: rows)
    monkeypatch.setattr(overview, "_RATE_TAIL_CACHE", (0.0, []))
    status = overview._build_all_status()[sid]
    assert status["five_hour_pct"] is None
    assert status["five_hour_resets_at"] is None
    assert status["seven_day_pct"] == (7 if rows else None)
