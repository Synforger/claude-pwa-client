"""A tab started again with a new conversation (the rollover, or the operator's restart) has the account of its new
conversation chosen between the end of the old claude and the start of the new one, under the tab's claim
(`routes/sessions.py::restart_session`, `account_hold/new_conversation_account.py`)."""
from __future__ import annotations

import asyncio

# The backend's modules are read inside the tests, under the test settings: read at the top of the file they would
# take the real settings and break later test files.


def _restart_with(monkeypatch, isolated_state) -> tuple[object, str, list[str]]:
    import backend.account_hold.new_conversation_account as new_conversation
    import backend.jsonl.routes as jsonl_routes
    import backend.routes.sessions as sessions_routes
    import backend.terminal.routes as pty_routes
    order: list[str] = []

    async def stopped(_sid):
        order.append("stop")
        return True

    async def spawn(_sid, **_kwargs):
        order.append("spawn")

    monkeypatch.setattr(isolated_state, "save_sessions_meta", lambda: None)
    monkeypatch.setattr(sessions_routes, "stop_tab_claude", stopped)
    monkeypatch.setattr(sessions_routes.jsonl_watcher, "get_jsonl_for", lambda sid: None)
    monkeypatch.setattr(sessions_routes.jsonl_watcher, "unregister", lambda sid: None)
    monkeypatch.setattr(jsonl_routes, "request_sid_tail_reset", lambda sid: None)
    monkeypatch.setattr(pty_routes, "ensure_pty_session_for", spawn)
    monkeypatch.setattr(new_conversation, "choose_account_for_new_conversation", lambda _sid: order.append("account"))
    tab = isolated_state.register_session(next(iter(isolated_state._agents())), title="Chat")
    return sessions_routes, tab.id, order


def test_the_account_is_chosen_after_the_old_claude_ends_and_before_the_new_one_starts(monkeypatch, isolated_state):
    sessions_routes, sid, order = _restart_with(monkeypatch, isolated_state)
    assert asyncio.run(sessions_routes.restart_session(sid))["ok"] is True
    assert order == ["stop", "account", "spawn"]


def test_a_tab_another_feature_holds_starts_again_on_its_account(monkeypatch, isolated_state):
    from backend.accounts.tab_claim import claimed
    sessions_routes, sid, order = _restart_with(monkeypatch, isolated_state)
    with claimed(sid):
        assert asyncio.run(sessions_routes.restart_session(sid))["ok"] is True
    assert order == ["stop", "spawn"]
