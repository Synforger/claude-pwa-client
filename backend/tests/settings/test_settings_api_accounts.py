"""The API wallets on the settings screen (`settings_view.py`): shown beside the accounts, read-only, and never counted as
an account that tabs are routed to (= the account fallback, the account hold and the new-conversation list are untouched)."""
from __future__ import annotations

import json
from datetime import datetime

import pytest
from fastapi import FastAPI
from starlette.testclient import TestClient

import backend._common.config as config
from backend.account_fallback import fallback_settings
from backend.account_hold import hold_settings
from backend.api_tabs import stream
from backend.routes import accounts as accounts_routes
from backend.routes import settings as settings_routes
from backend.settings import settings_view
from backend.tests.async_run import run
from backend.tests.settings.conftest import SETTINGS


@pytest.fixture
def with_wallet(config_file, monkeypatch, isolated_state, tmp_path):
    """The settings of the screen's tests plus one wallet whose spend file is under the test's folder."""
    spend = tmp_path / "spend.json"
    config_file.write_text(json.dumps({**SETTINGS, "api_accounts": {"api": {"display_name": "API", "spend": str(spend)}}},
                                      indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    config.get_config.cache_clear()
    monkeypatch.setattr(settings_view, "read_all_rate_limits_tail", lambda: [])
    stream.__init__()
    yield spend
    stream.__init__()


def test_a_wallet_is_not_an_account_anywhere_that_walks_the_accounts(with_wallet):
    assert list(config.ACCOUNTS) == ["work", "personal"]                    # the number of accounts did not change
    assert set(fallback_settings.read_rules()) == {"work"} and set(hold_settings.read_rules()) == {"personal"}
    assert [account["id"] for account in settings_view.build_view()["accounts"]] == ["work", "personal"]
    app = FastAPI()
    app.include_router(accounts_routes.router)
    assert [row["id"] for row in TestClient(app).get("/accounts").json()] == ["work", "personal"]


def test_the_wallet_row_carries_this_months_spend_and_the_limit(with_wallet):
    with_wallet.write_text(json.dumps({"month": datetime.now().strftime("%Y-%m"), "spent": 123, "limit": 1000,
                                       "currency": "JPY", "updated_at": "2026-11-18T12:00:00+09:00"}))
    run(stream.poll())
    app = FastAPI()
    app.include_router(settings_routes.router)
    view = TestClient(app).get("/settings").json()
    assert [wallet["id"] for wallet in view["api_accounts"]] == ["api"]
    assert view["api_accounts"][0]["display_name"] == "API"
    assert (view["api_accounts"][0]["spend"]["spent"], view["api_accounts"][0]["spend"]["limit"],
            view["api_accounts"][0]["spend"]["currency"]) == (123, 1000, "JPY")


def test_a_wallet_with_no_figure_shows_none_and_no_wallet_shows_an_empty_list(with_wallet, config_file):
    assert settings_view.build_view()["api_accounts"][0]["spend"] is None   # the file is not there
    config_file.write_text(json.dumps(SETTINGS))
    config.get_config.cache_clear()
    assert settings_view.build_view()["api_accounts"] == []


def test_the_screen_cannot_write_a_wallet(with_wallet):
    app = FastAPI()
    app.include_router(settings_routes.router)
    reply = TestClient(app).put("/settings", json={"api_accounts": {"api": {"display_name": "Other"}}})
    assert reply.status_code == 400 and reply.json()["detail"]["code"] == "settings_rejected"
