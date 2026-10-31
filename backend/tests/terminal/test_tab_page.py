"""A tab's top page (`terminal/tab_page.py`, `terminal/page_template.py`): made from the agent's template when
the tab's tier is recorded, never over a page that exists, and told to the screen by the memo read."""
from __future__ import annotations

import asyncio

import pytest
from fastapi import FastAPI
from starlette.testclient import TestClient

from backend._generated import http_endpoints as http
from backend.terminal import pty_discover, tab_tier
from backend.terminal.page_template import fill_template, template_file
from backend.terminal.tab_memo import page_file, page_path
from backend.terminal.tab_page import existing_page, make_page

TEMPLATE = '<html><title>{{title}}</title><p>階層: {{tier}}</p><p>{{unknown}} {title} {{tier}}</p></html>'


@pytest.fixture
def tab(a_tab):
    return a_tab


@pytest.fixture
def template(agent_folder):
    path = template_file(agent_folder)
    path.parent.mkdir(parents=True)
    path.write_text(TEMPLATE, encoding="utf-8")
    return path


def started_in(monkeypatch, tab, tier):
    tab.tier = tier


# --- The fill-in (pure) ---

def test_the_template_marks_are_filled_and_every_other_character_is_kept():
    assert fill_template(TEMPLATE, title="設計", tier="projects/alpha") == (
        '<html><title>設計</title><p>階層: projects/alpha</p><p>{{unknown}} {title} projects/alpha</p></html>')


def test_the_title_and_tier_are_escaped_for_html():
    out = fill_template("<h1>{{title}}</h1><i>{{tier}}</i>", title='<script>x("&")</script>', tier="a&b")
    assert out == "<h1>&lt;script&gt;x(&quot;&amp;&quot;)&lt;/script&gt;</h1><i>a&amp;b</i>"


def test_a_mark_inside_the_title_is_not_filled_a_second_time():
    assert fill_template("{{title}}|{{tier}}", title="{{tier}}", tier="normal") == "{{tier}}|normal"


def test_the_template_is_one_per_agent_and_the_page_sits_next_to_the_memo(tmp_path):
    assert template_file(tmp_path) == tmp_path / "pages" / "_template-tab" / "index.html"
    assert page_file(tmp_path, "ses_1") == tmp_path / "pages" / "ses_1" / "index.html"
    with pytest.raises(ValueError):
        page_file(tmp_path, "../x")


# --- Making the page ---

def test_a_tab_of_the_agent_folder_gets_its_page_from_the_template(tab, template, agent_folder, monkeypatch):
    started_in(monkeypatch, tab, "normal")
    made = make_page(tab.id)
    assert made == agent_folder / "pages" / tab.id / "index.html"
    assert made.read_text(encoding="utf-8") == fill_template(TEMPLATE, title="A", tier="normal")
    assert page_path(tab.id) == made and existing_page(tab.id) == made


def test_a_tab_started_in_a_tier_gets_its_page_in_that_tier_folder(tab, template, agent_folder, monkeypatch):
    (agent_folder / "projects" / "alpha").mkdir(parents=True)
    started_in(monkeypatch, tab, "projects/alpha")
    made = make_page(tab.id)
    assert made == agent_folder / "projects" / "alpha" / "pages" / tab.id / "index.html"
    assert "階層: projects/alpha" in made.read_text(encoding="utf-8")
    assert not (agent_folder / "pages" / tab.id).exists()


def test_a_page_that_exists_is_never_touched(tab, template, agent_folder, monkeypatch):
    started_in(monkeypatch, tab, "normal")
    page = agent_folder / "pages" / tab.id / "index.html"
    page.parent.mkdir(parents=True)
    page.write_text("<p>書き込み済み</p>", encoding="utf-8")
    assert make_page(tab.id) is None
    assert page.read_text(encoding="utf-8") == "<p>書き込み済み</p>"


def test_the_page_is_made_once(tab, template, monkeypatch):
    started_in(monkeypatch, tab, "normal")
    assert make_page(tab.id) is not None
    assert make_page(tab.id) is None


def test_an_agent_without_a_template_gets_nothing(tab, agent_folder, monkeypatch):
    started_in(monkeypatch, tab, "normal")
    assert make_page(tab.id) is None
    assert not (agent_folder / "pages").exists()
    assert existing_page(tab.id) is None


def test_a_tab_whose_tier_is_not_known_gets_nothing(tab, template, agent_folder):
    assert make_page(tab.id) is None
    assert not (agent_folder / "pages" / tab.id).exists()


def test_a_template_that_cannot_be_read_leaves_no_page_and_does_not_raise(tab, template, agent_folder, monkeypatch):
    started_in(monkeypatch, tab, "normal")
    template.write_bytes(b"\xff\xfe\x00bad")
    assert make_page(tab.id) is None
    assert not (agent_folder / "pages" / tab.id).exists()


def test_the_title_of_the_tab_is_what_the_page_shows(a_tab, template, isolated_state, monkeypatch):
    isolated_state.sessions_meta[a_tab.id].title = "<b>調査</b>"
    started_in(monkeypatch, a_tab, "normal")
    assert "<title>&lt;b&gt;調査&lt;/b&gt;</title>" in make_page(a_tab.id).read_text(encoding="utf-8")


# --- Every way a tab's tier is recorded makes the page ---

def test_finding_the_claude_of_a_tab_makes_its_page(tab, template, monkeypatch):
    monkeypatch.setattr(pty_discover, "tmux_pane_pids", lambda sid: [111])
    monkeypatch.setattr(pty_discover, "_find_claude_descendant_info", lambda pid: (222, 1.0, "/work"))
    monkeypatch.setattr(tab_tier, "read_tier", lambda pid: "normal")
    monkeypatch.setattr(pty_discover.sessions_overview, "notify", lambda: None)
    import backend.jsonl.jsonl_watcher as jsonl_watcher  # noqa: PLC0415
    monkeypatch.setattr(jsonl_watcher, "register_pending", lambda *args: None)
    asyncio.run(pty_discover.register_claude_when_ready(tab.id, max_wait=2.0, interval=0.01))
    assert existing_page(tab.id) is not None


def test_reading_the_tier_again_at_session_start_makes_a_page_that_is_missing(tab, template, monkeypatch):
    monkeypatch.setattr(pty_discover, "claude_pid_in_pane", lambda sid: 222)
    monkeypatch.setattr(tab_tier, "read_tier", lambda pid: "normal")
    monkeypatch.setattr(pty_discover.sessions_overview, "notify", lambda: None)
    asyncio.run(pty_discover.refresh_tier(tab.id))
    page = existing_page(tab.id)
    assert page is not None
    page.write_text("<p>編集後</p>", encoding="utf-8")
    asyncio.run(pty_discover.refresh_tier(tab.id))
    assert page.read_text(encoding="utf-8") == "<p>編集後</p>"


# --- The memo read tells the screen where the page is ---

@pytest.fixture
def client(tab):
    import backend.routes.notes as notes  # noqa: PLC0415
    app = FastAPI()
    app.include_router(notes.router)
    return TestClient(app)


def test_the_memo_read_names_the_page_when_it_exists_and_null_when_not(client, tab, template, monkeypatch):
    started_in(monkeypatch, tab, "normal")
    assert client.get(f"/sessions/{tab.id}/note").json()["page"] is None
    made = make_page(tab.id)
    body = client.get(f"/sessions/{tab.id}/note").json()
    assert body["page"] == str(made)
    http.GetSessionsSidNoteResponse.model_validate(body)
