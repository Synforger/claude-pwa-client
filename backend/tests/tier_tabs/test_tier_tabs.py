"""Tier tabs: the tabs the backend places for an agent's tiers, how their first message starts claude in the
tier, and `POST /tier-tabs`.

tmux and claude are not started: launching and typing into the terminal are replaced, so what is seen is the
tabs that get registered, the record of tiers, and what is typed into a placed tab when a message reaches it.
"""

from __future__ import annotations

import asyncio
import json
import re
from pathlib import Path

import pytest
from fastapi import FastAPI
from starlette.testclient import TestClient

import backend._common.config as config_mod
import backend.rollover.rollover as rollover_watch
from backend._common.state import SessionDef
from backend.jsonl.jsonl_predicates import (
    AGENT_MESSAGE_OPENING,
    ROLLOVER_OPENING,
    TAB_OPEN_OPENING,
    is_agent_message,
    is_client_message,
)
from backend.routes import agent_messages
from backend.routes import tier_tabs as routes
from backend.terminal import first_message, input_ready, session_resolver, tab_tier
from backend.tier_tabs import record, tier_tabs
from backend.tier_tabs.envelope import envelope, tab_name
from backend.voice_call.rules import shown_user_text

ROOT = Path(__file__).resolve().parents[3]


def make_agent(folder: Path) -> Path:
    """An agent folder with two projects, one subproject, and folders that are not tiers."""
    for tier in ("projects/A/subprojects/S", "projects/B", "projects/_archive/old", "projects/.hidden",
                 "projects/B/subprojects/_draft"):
        (folder / tier).mkdir(parents=True, exist_ok=True)
    (folder / "projects/notes.md").write_text("not a folder")
    return folder


@pytest.fixture
def agent(tmp_path) -> Path:
    return make_agent(tmp_path / "agents" / "main")


@pytest.fixture
def configured(monkeypatch, tmp_path, isolated_state, agent) -> None:
    """MAIN has tier tabs; WORK (with a child agent in the same folder) does not."""
    path = tmp_path / "config.json"
    agents = {
        "agent_a": {"cwd": str(agent), "display_name": "MAIN", "launch_alias": "main", "launcher": True,
                    "tier_tabs": True},
        "agent_b": {"cwd": str(tmp_path / "agents" / "work"), "display_name": "WORK", "launch_alias": "work",
                    "launcher": True, "child_agent": "agent_sub"},
        "agent_sub": {"cwd": str(tmp_path / "agents" / "work"), "launch_alias": "work --child", "launcher": True},
    }
    path.write_text(json.dumps({"uploads_tmp": str(tmp_path / "uploads"), "agents": agents}))
    monkeypatch.setattr(config_mod, "CONFIG_PATH", path)
    config_mod.get_config.cache_clear()
    # the session resolver holds the agents it read when it was imported
    monkeypatch.setattr(session_resolver, "AGENTS", agents)
    monkeypatch.setattr(record, "TIER_TABS_PATH", tmp_path / "data" / "tier_tabs.json")


def run(coroutine):
    return asyncio.run(coroutine)


def client(address: str | None = None) -> TestClient:
    app = FastAPI()
    app.include_router(routes.router)
    return TestClient(app, client=(address, 50000)) if address else TestClient(app)


def titles(state, tabs: list[str]) -> list[str]:
    return [state.sessions_meta[sid].title for sid in tabs]


# --- the envelope and the name -------------------------------------------------------------------------------

def test_the_envelope_is_a_client_message_that_carries_the_tier():
    text = envelope("projects/music/subprojects/demo")
    assert text == f"{TAB_OPEN_OPENING}\n<tab-open>\ntier=projects/music/subprojects/demo\n</tab-open>"
    assert is_client_message(text) and not is_agent_message(text)
    # the agent's launcher reads the block the same way as `<child-start>` (= its `tier=` line)
    block = re.search(r"<tab-open>\n(.*?)\n</tab-open>", text, re.S).group(1)
    assert block.splitlines() == ["tier=projects/music/subprojects/demo"]


@pytest.mark.parametrize("tier, name", [
    ("normal", "MAIN"),
    ("projects/music", "music"),
    ("projects/music/subprojects/demo", "music・demo"),
])
def test_a_tab_is_named_after_its_tier(tier, name):
    assert tab_name(tier, "MAIN") == name


def test_the_call_window_does_not_show_the_envelope():
    assert shown_user_text(envelope("normal")) is None


def test_the_rollover_watch_does_not_take_the_envelope_for_the_operator_typing():
    row = json.dumps({"type": "user", "message": {"role": "user", "content": envelope("normal")}}).encode()
    assert rollover_watch._decisive(row) is None


def test_the_opening_line_is_the_same_everywhere_it_is_written():
    """The backend writes the first line, the screen reads it and the docs tell other tools about it."""
    assert f"'{TAB_OPEN_OPENING}'" in (ROOT / "frontend/src/features/chat/agentMessage.js").read_text()
    assert TAB_OPEN_OPENING in (ROOT / "docs/reference/tier-tabs.md").read_text()


# --- the tiers of a folder -----------------------------------------------------------------------------------

def test_the_tiers_are_the_agent_its_projects_and_their_subprojects(agent):
    assert tier_tabs.folder_tiers(agent) == ["normal", "projects/A", "projects/A/subprojects/S", "projects/B"]


def test_a_folder_without_projects_has_only_normal(tmp_path):
    assert tier_tabs.folder_tiers(tmp_path) == ["normal"]


# --- placing the tabs of new tiers ---------------------------------------------------------------------------

def test_every_tier_gets_one_tab_placed_without_a_claude(configured, isolated_state):
    tabs = tier_tabs.place_new_tiers()
    assert titles(isolated_state, tabs) == ["MAIN", "A", "A・S", "B"]
    metas = [isolated_state.sessions_meta[sid] for sid in tabs]
    assert [m.tier_tab for m in metas] == ["normal", "projects/A", "projects/A/subprojects/S", "projects/B"]
    assert all(m.agent_id == "agent_a" and not m.child for m in metas)
    assert record.load() == {"agent_a": {"normal", "projects/A", "projects/A/subprojects/S", "projects/B"}}


def test_a_placed_tab_works_in_its_tier_before_its_claude_starts(configured, isolated_state):
    [first, *_] = tier_tabs.place_new_tiers()
    assert tab_tier.tab_tier(first) == "normal"
    assert isolated_state.sessions_meta[first].to_dict()["tier_tab"] == "normal"
    # once its claude runs, the tier the claude was given wins
    isolated_state.sessions_meta[first].tier = "projects/B"
    assert tab_tier.tab_tier(first) == "projects/B"


def test_a_closed_tab_is_not_placed_again_but_a_new_folder_gets_one(configured, isolated_state, agent):
    tabs = tier_tabs.place_new_tiers()
    del isolated_state.sessions_meta[tabs[1]]
    assert tier_tabs.place_new_tiers() == []
    (agent / "projects/C").mkdir()
    assert titles(isolated_state, tier_tabs.place_new_tiers()) == ["C"]


def test_a_tier_that_already_has_a_tab_is_recorded_without_another(configured, isolated_state):
    isolated_state.sessions_meta["ses_hand"] = SessionDef(id="ses_hand", agent_id="agent_a", title="music",
                                                          created_at=0, tier="projects/A")
    assert titles(isolated_state, tier_tabs.place_new_tiers()) == ["MAIN", "A・S", "B"]
    assert "projects/A" in record.load()["agent_a"]


def test_a_child_tab_in_a_tier_does_not_count_as_its_tab(configured, isolated_state):
    isolated_state.sessions_meta["ses_kid"] = SessionDef(id="ses_kid", agent_id="agent_a", title="kid",
                                                         created_at=0, parent_id="ses_x", child=True,
                                                         tier="projects/B")
    assert "B" in titles(isolated_state, tier_tabs.place_new_tiers())


def test_agents_without_tier_tabs_or_a_launcher_get_nothing(configured, isolated_state, tmp_path, agent):
    path = tmp_path / "config.json"
    agents = {"agent_a": {"cwd": str(agent), "launch_alias": "main", "tier_tabs": True},
              "agent_b": {"cwd": str(agent), "launch_alias": "main", "launcher": True}}
    path.write_text(json.dumps({"agents": agents}))
    config_mod.get_config.cache_clear()
    assert tier_tabs.place_new_tiers() == [] and not isolated_state.sessions_meta


def test_the_loop_waits_before_its_first_look(configured, monkeypatch):
    looked: list[float] = []

    def fake_look():
        looked.append(asyncio.get_running_loop().time())
        raise asyncio.CancelledError

    monkeypatch.setattr(tier_tabs, "place_new_tiers", fake_look)

    async def main():
        start = asyncio.get_running_loop().time()
        with pytest.raises(asyncio.CancelledError):
            await tier_tabs.tier_tabs_loop(interval_sec=1, first_delay_sec=0.05)
        return start

    start = run(main())
    assert len(looked) == 1 and looked[0] - start >= 0.05


# --- the first message of a placed tab -----------------------------------------------------------------------

@pytest.fixture
def launched(configured, monkeypatch, tmp_path) -> list[tuple[str, str]]:
    """What a placed tab's terminal receives: ("launch", the first message the launcher starts claude with)
    and ("send", a message typed once claude takes input)."""
    events: list[tuple[str, str]] = []

    async def fake_ensure(session_id, **_):
        return None

    async def typeable(session_id, timeout):
        return True

    def fake_keys(session_id, text=None, key=None, enter=False):
        if text:
            message_file = Path(text.split("--first-message-file ", 1)[1].strip("'"))
            events.append(("launch", message_file.read_text(encoding="utf-8")))
        return True

    async def fake_register(session_id, max_wait):
        return None

    async def fake_send(session_id, payload, idempotency_key=None):
        events.append(("send", payload["text"]))
        return {"ok": True}

    monkeypatch.setattr(first_message, "ensure_pty_session_for", fake_ensure)
    monkeypatch.setattr(first_message, "claude_in_pane", lambda sid: False)
    monkeypatch.setattr(first_message, "wait_until_typeable", typeable)
    monkeypatch.setattr(first_message, "tmux_send_keys", fake_keys)
    monkeypatch.setattr(first_message, "register_claude_when_ready", fake_register)
    monkeypatch.setattr("backend.terminal.routes.pty_send", fake_send)
    monkeypatch.setattr(first_message, "_uploads_dir", lambda: tmp_path / "uploads")
    return events


async def deliver(session_id: str, text: str):
    result = await first_message.launch_with_first_message(session_id, text)
    # what claude's start would do: the launcher's session reports in, the next message goes in
    input_ready.mark_ready(session_id)
    await asyncio.gather(*first_message._following)
    return result


def test_the_operator_s_first_message_starts_claude_in_the_tab_s_tier(launched, isolated_state):
    tabs = tier_tabs.place_new_tiers()
    result = run(deliver(tabs[2], "what is left on the mix?"))
    assert result == {"ok": True, "launched": True}
    # the envelope starts claude in the tier, and what was sent goes in as the next message, untouched
    assert launched == [("launch", envelope("projects/A/subprojects/S")), ("send", "what is left on the mix?")]


def test_a_message_from_another_tab_also_goes_in_after_the_envelope(launched, isolated_state):
    tabs = tier_tabs.place_new_tiers()
    relayed = f'{AGENT_MESSAGE_OPENING}\n<agent-message from="MAIN" session="ses_n">\nplease check\n</agent-message>'
    run(deliver(tabs[3], relayed))
    assert launched == [("launch", envelope("projects/B")), ("send", relayed)]


def test_a_rollover_carries_its_own_tier_and_starts_as_it_is(launched, isolated_state):
    tabs = tier_tabs.place_new_tiers()
    rolled = f'{ROLLOVER_OPENING}\n<session-rollover phase="start">\ntier=projects/B\nmode=wait\n</session-rollover>'
    run(deliver(tabs[3], rolled))
    assert launched == [("launch", rolled)]


def test_a_tab_that_was_not_placed_starts_with_what_was_sent(launched, isolated_state):
    isolated_state.sessions_meta["ses_hand"] = SessionDef(id="ses_hand", agent_id="agent_a", title="hand",
                                                          created_at=0)
    run(deliver("ses_hand", "projects/A please"))
    assert launched == [("launch", "projects/A please")]


# --- messages to a placed tab --------------------------------------------------------------------------------

def test_a_placed_tab_takes_messages_before_its_claude_starts(configured, isolated_state, monkeypatch):
    tabs = tier_tabs.place_new_tiers()
    monkeypatch.setattr(agent_messages, "claude_in_pane", lambda sid: False)
    assert agent_messages._tab_reachable(tabs[0])
    isolated_state.sessions_meta["ses_hand"] = SessionDef(id="ses_hand", agent_id="agent_a", title="hand",
                                                          created_at=0)
    assert not agent_messages._tab_reachable("ses_hand")


def test_a_message_to_a_placed_tab_is_checked_as_for_a_conversation_that_read_nothing(configured, isolated_state,
                                                                                         monkeypatch):
    tabs = tier_tabs.place_new_tiers()
    monkeypatch.setattr(agent_messages, "claude_in_pane", lambda sid: False)
    monkeypatch.setattr(agent_messages, "jsonl_path_for_session", lambda sid: None)
    monkeypatch.setattr(config_mod, "AGENT_MESSAGE_CHECK", ["true"], raising=False)
    judged: list[str] = []

    async def fake_judge(session, text, receiver):
        judged.append(session)

    monkeypatch.setattr(agent_messages, "judge", fake_judge)
    run(agent_messages.check(tabs[1], "hello"))
    assert judged == [f"tier-tab:{tabs[1]}"]


# --- POST /tier-tabs (= `tabs open <tier>`) -------------------------------------------------------------------

def test_a_closed_tier_tab_is_placed_again_on_request(configured, isolated_state, agent):
    tabs = tier_tabs.place_new_tiers()
    del isolated_state.sessions_meta[tabs[3]]
    with client() as c:
        r = c.post("/tier-tabs", data={"agent_dir": str(agent), "tier": "projects/B"})
    assert r.status_code == 200
    body = r.json()
    assert body["title"] == "B" and body["tier_tab"] == "projects/B" and body["child"] is False


def test_a_tier_that_has_a_tab_is_refused(configured, isolated_state, agent):
    tier_tabs.place_new_tiers()
    with client() as c:
        r = c.post("/tier-tabs", data={"agent_dir": str(agent), "tier": "projects/A"})
    assert r.status_code == 409 and r.json()["detail"]["code"] == "tier_tab_exists"


@pytest.mark.parametrize("tier", ["projects/Z", "projects/_archive", "../outside", "/abs"])
def test_a_tier_the_agent_has_no_folder_for_is_refused(configured, agent, tier):
    with client() as c:
        r = c.post("/tier-tabs", data={"agent_dir": str(agent), "tier": tier})
    assert r.status_code == 400 and r.json()["detail"]["code"] == "tier_tab_unknown_tier"


def test_the_agent_is_the_one_whose_folder_is_given_not_its_child_agent(configured, tmp_path, isolated_state):
    work = make_agent(tmp_path / "agents" / "work")
    with client() as c:
        r = c.post("/tier-tabs", data={"agent_dir": str(work), "tier": "projects/A"})
        unknown = c.post("/tier-tabs", data={"agent_dir": str(tmp_path / "nobody"), "tier": "normal"})
    assert r.status_code == 200 and r.json()["agent_id"] == "agent_b"
    assert unknown.status_code == 400 and unknown.json()["detail"]["code"] == "tier_tab_unknown_agent"


def test_the_endpoint_answers_only_this_machine(configured, agent):
    with client("100.64.0.9") as c:
        r = c.post("/tier-tabs", data={"agent_dir": str(agent), "tier": "normal"})
    assert r.status_code == 403
