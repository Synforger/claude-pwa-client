"""The table of API tabs and wallets that `config.json` declares (`backend/api_tabs/api_tab_table.py`)."""
from __future__ import annotations

import logging

import pytest

import backend._common.config as config_mod
from backend.api_tabs import api_tab_table, current_table, is_api_tab
from backend.tests.api_tabs.samples import TAB_ID, write_config

LOGGER = "backend.api_tabs.api_tab_table"


def test_a_declared_tab_gets_the_api_prefix_and_the_wallet_it_names(api_env):
    tab = current_table().tab(TAB_ID)
    assert (tab.name, tab.title, tab.agent_id, tab.account, tab.record) == (
        "support-bot", "Support bot", "agent_a", "api", api_env.record)
    assert current_table().ids() == [TAB_ID]
    assert is_api_tab(TAB_ID) and not is_api_tab("ses_abc") and not is_api_tab("api_other")


@pytest.mark.parametrize("name", ["Line", "support_bot", "support bot", "a:b", "a,b", "日本語", "ok\n"])
def test_a_row_whose_name_leaves_a_to_z_digits_and_hyphen_is_not_read_and_warns(api_env, caplog, name):
    write_config(api_env, api_accounts={"api": {}},
                 api_tabs={name: {"agent_id": "agent_a", "record": str(api_env.record)},
                           "fine": {"agent_id": "agent_a", "record": str(api_env.record)}})
    with caplog.at_level(logging.WARNING, logger=LOGGER):
        table = current_table()
    assert table.ids() == ["api_fine"]                  # the other row stays
    assert [r.getMessage() for r in caplog.records] == [
        f"api tab: skipped {name!r}: the name must match [a-z0-9-]+"]


def test_a_row_naming_an_agent_that_is_not_configured_is_not_read_and_warns(api_env, caplog):
    write_config(api_env, api_tabs={"lost": {"agent_id": "nobody", "record": str(api_env.record)}})
    with caplog.at_level(logging.WARNING, logger=LOGGER):
        assert current_table().ids() == []
    assert "api tab: skipped lost: agent_id 'nobody' is not in agents" in caplog.text


def test_a_record_that_is_not_an_absolute_path_is_not_read(api_env, caplog):
    write_config(api_env, api_tabs={"near": {"agent_id": "agent_a", "record": "conversations/near.jsonl"}})
    with caplog.at_level(logging.WARNING, logger=LOGGER):
        assert current_table().ids() == []
    assert "api tab: skipped near: record must be an absolute path" in caplog.text


def test_a_tab_without_an_account_names_the_api_wallet_and_without_a_title_its_name(api_env):
    write_config(api_env, api_tabs={"plain": {"agent_id": "agent_a", "record": str(api_env.record)}})
    tab = current_table().tab("api_plain")
    assert (tab.account, tab.title) == ("api", "plain")


def test_a_tab_naming_a_wallet_that_is_not_declared_is_kept_with_a_warning(api_env, caplog):
    write_config(api_env, api_tabs={"odd": {"agent_id": "agent_a", "account": "ghost", "record": str(api_env.record)}})
    with caplog.at_level(logging.WARNING, logger=LOGGER):
        assert current_table().ids() == ["api_odd"]
    assert "api tab: odd names account ghost, which is not in api_accounts" in caplog.text


def test_a_receiver_is_found_by_the_id_or_by_the_title(api_env):
    table = current_table()
    assert table.find(TAB_ID).id == TAB_ID and table.find("Support bot").id == TAB_ID
    assert table.find("ses_abc") is None and table.find("support-bot") is None


def test_loading_writes_one_line_for_each_tab_and_wallet(api_env, caplog):
    with caplog.at_level(logging.INFO, logger=LOGGER):
        current_table()
    lines = [r.getMessage() for r in caplog.records]
    assert f"api tab: loaded {TAB_ID} record={api_env.record} exists=False" in lines
    assert f"api account: loaded api spend={api_env.spend}" in lines


def test_the_table_is_read_again_only_when_the_configuration_was_read_again(api_env, caplog):
    first = current_table()
    with caplog.at_level(logging.INFO, logger=LOGGER):
        assert current_table() is first and caplog.records == []          # the same configuration: nothing is parsed
    write_config(api_env, api_tabs={})
    assert current_table() is not first and current_table().ids() == []   # what `reload_config` makes visible
    assert config_mod.get_config() is config_mod.get_config()
