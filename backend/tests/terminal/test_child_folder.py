"""Clearing what the client wrote for a closed child tab (`terminal/child_folder.py`): the memo and an untouched
top page go, the folder goes once it is empty, and a page the child wrote stays. A page the client wrote is told untouched by the fingerprint kept
when it was made, even after the template changed. A tab that is not a child keeps its memo. At start, the untouched top
pages an earlier version made for child and fork tabs go, and nothing else does."""
from __future__ import annotations

import pytest

from backend.terminal.child_folder import clear_child_folder, clear_derived_pages
from backend.terminal.page_template import fill_template, page_fingerprint, pages_root_from, template_file

TEMPLATE = "<html><title>{{title}}</title><p>{{tier}}</p></html>"


@pytest.fixture
def family(isolated_state, agent_folder, monkeypatch):
    """A parent working in `projects/P` and its child, with the agent's template and the tier folder."""
    monkeypatch.setattr(isolated_state, "save_sessions_meta", lambda: None)
    (agent_folder / "projects" / "P").mkdir(parents=True)
    template = template_file(agent_folder)
    template.parent.mkdir(parents=True)
    template.write_text(TEMPLATE, encoding="utf-8")
    parent = isolated_state.register_session("agent_a", title="lead", tier="projects/P")
    child = isolated_state.register_session("agent_a", title="kid", parent_id=parent.id, child=True, tier="projects/P")
    return parent, child, agent_folder


def _write(folder, *, memo=True, page=None, more=None):
    folder.mkdir(parents=True, exist_ok=True)
    if memo:
        (folder / "memo.md").write_text("- 状態: 完了\n", encoding="utf-8")
    if page is not None:
        (folder / "index.html").write_text(page, encoding="utf-8")
    for name in more or []:
        (folder / name).write_text("<p>explained</p>", encoding="utf-8")


def test_the_memo_the_untouched_page_and_the_empty_folder_go(family):
    _parent, child, agent = family
    folder = agent / "projects" / "P" / "pages" / child.id
    _write(folder, page=fill_template(TEMPLATE, title="kid", tier="projects/P", pages_root="../../../../pages"))
    clear_child_folder(child.id)
    assert not folder.exists()


def test_a_page_that_only_gained_a_script_line_is_untouched(family, monkeypatch):
    # 意図: 階層の全部のページに部品 (= 横の目次) を足す道具が 1 行足しただけのトップページも、 閉じた時に片付ける
    _parent, child, agent = family
    template = "<html>\n<head><title>{{title}}</title></head>\n<body><p>{{tier}}</p></body>\n</html>\n"
    template_file(agent).write_text(template, encoding="utf-8")
    folder = agent / "projects" / "P" / "pages" / child.id
    filled = fill_template(template, title="kid", tier="projects/P", pages_root="../../../../pages")
    _write(folder, page=filled.replace("</head>", '</head>\n<script src="../_common/toc-sidebar.js" defer></script>'))
    clear_child_folder(child.id)
    assert not folder.exists()


def test_a_page_with_a_script_line_and_its_own_words_stays(family):
    _parent, child, agent = family
    folder = agent / "projects" / "P" / "pages" / child.id
    page = fill_template(TEMPLATE, title="kid", tier="projects/P", pages_root="../../../../pages") + '\n<script src="x.js"></script>\n<p>found</p>'
    _write(folder, page=page)
    clear_child_folder(child.id)
    assert (folder / "index.html").is_file()


def test_a_page_the_child_wrote_stays_and_so_does_its_folder(family):
    _parent, child, agent = family
    folder = agent / "projects" / "P" / "pages" / child.id
    _write(folder, page="<p>the child's own top page</p>", more=["findings.html"])
    clear_child_folder(child.id)
    assert sorted(path.name for path in folder.iterdir()) == ["findings.html", "index.html"]


def test_a_child_that_started_in_another_tier_is_cleared_there_too(family):
    _parent, child, agent = family
    child.tier = "normal"  # started in the wrong tier: its page is in the agent's folder, its memo in the parent's
    wrong = agent / "pages" / child.id
    _write(wrong, page=fill_template(TEMPLATE, title="kid", tier="normal", pages_root=".."))
    right = agent / "projects" / "P" / "pages" / child.id
    _write(right)
    clear_child_folder(child.id)
    assert not wrong.exists() and not right.exists()


def test_a_tab_that_is_not_a_child_keeps_its_memo(family):
    parent, _child, agent = family
    folder = agent / "projects" / "P" / "pages" / parent.id
    _write(folder, page=fill_template(TEMPLATE, title="lead", tier="projects/P", pages_root="../../../../pages"))
    assert clear_child_folder(parent.id) == []
    assert (folder / "memo.md").is_file() and (folder / "index.html").is_file()


# --- A page the client wrote, and a template that changed after that ---

NEW_TEMPLATE = "<html><title>{{title}}</title><p>newer layout: {{tier}}</p></html>"


def _earlier_page(tab, agent, tier="projects/P"):
    """The top page an earlier version of the client made for `tab` in `tier` from the template, with its fingerprint
    kept on the tab as that version kept it."""
    tab.tier = tier
    folder = agent.joinpath(*tier.split("/"), "pages", tab.id)
    text = fill_template(template_file(agent).read_text(encoding="utf-8"), title=tab.title, tier=tier,
                         pages_root=pages_root_from(agent, folder))
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "index.html").write_text(text, encoding="utf-8")
    tab.top_page_sha = page_fingerprint(text)
    return folder / "index.html"


def _made_page(child, agent, monkeypatch):
    return _earlier_page(child, agent)


def test_an_untouched_page_goes_after_the_template_changed(family, monkeypatch):
    _parent, child, agent = family
    page = _made_page(child, agent, monkeypatch)
    template_file(agent).write_text(NEW_TEMPLATE, encoding="utf-8")
    clear_child_folder(child.id)
    assert not page.parent.exists()


def test_a_page_with_one_script_line_goes_after_the_template_changed(family, monkeypatch):
    _parent, child, agent = family
    page = _made_page(child, agent, monkeypatch)
    page.write_text(page.read_text(encoding="utf-8") + '\n<script src="../_common/toc.js" defer></script>', encoding="utf-8")
    template_file(agent).write_text(NEW_TEMPLATE, encoding="utf-8")
    clear_child_folder(child.id)
    assert not page.parent.exists()


def test_a_page_with_one_changed_character_stays_after_the_template_changed(family, monkeypatch):
    _parent, child, agent = family
    page = _made_page(child, agent, monkeypatch)
    page.write_text(page.read_text(encoding="utf-8").replace("kid", "kids"), encoding="utf-8")
    template_file(agent).write_text(NEW_TEMPLATE, encoding="utf-8")
    clear_child_folder(child.id)
    assert page.is_file()


def test_a_child_without_a_fingerprint_is_judged_by_the_template_as_it_is(family, monkeypatch):
    # 意図: 指紋を残す前に立てた子は、 今までどおり今の雛形との比較だけで決まる (= 雛形が変わっていれば残る)
    _parent, child, agent = family
    page = _made_page(child, agent, monkeypatch)
    child.top_page_sha = None
    template_file(agent).write_text(NEW_TEMPLATE, encoding="utf-8")
    clear_child_folder(child.id)
    assert page.is_file()
    template_file(agent).write_text(TEMPLATE, encoding="utf-8")
    clear_child_folder(child.id)
    assert not page.parent.exists()


def test_a_page_that_matches_neither_the_fingerprint_nor_the_template_stays(family, monkeypatch):
    _parent, child, agent = family
    page = _made_page(child, agent, monkeypatch)
    child.top_page_sha = "0" * 64
    template_file(agent).write_text(NEW_TEMPLATE, encoding="utf-8")
    clear_child_folder(child.id)
    assert page.is_file()


def test_an_untouched_page_with_the_way_up_is_told_untouched_in_a_deeper_tier(family, monkeypatch):
    # 意図: {{pages_root}} を埋めたページも、 指紋の無い子で今の雛形と比べて片付く (= 階層ごとに埋める値を合わせる)
    _parent, child, agent = family
    template_file(agent).write_text('<html><a href="{{pages_root}}/index.html">{{title}}</a></html>', encoding="utf-8")
    (agent / "projects" / "P" / "subprojects" / "S").mkdir(parents=True)
    page = _earlier_page(child, agent, "projects/P/subprojects/S")
    assert '"../../../../../../pages/index.html"' in page.read_text(encoding="utf-8")
    child.top_page_sha = None
    clear_child_folder(child.id)
    assert not page.parent.exists()


# --- At start: the pages an earlier version made for child and fork tabs ---

@pytest.fixture
def fork(family, isolated_state):
    """A fork of the parent, as `POST /sessions/<id>/fork` registers it (= `parent_id`, not a child)."""
    parent, _child, _agent = family
    return isolated_state.register_session("agent_a", title="lead fork", parent_id=parent.id, resume_session_id="c1",
                                           tier="projects/P")


def test_the_untouched_pages_of_a_child_and_a_fork_go_and_their_memos_stay(family, fork):
    parent, child, agent = family
    pages = [_earlier_page(tab, agent) for tab in (child, fork)]
    for page in pages:
        (page.parent / "memo.md").write_text("- 状態: 作業中\n", encoding="utf-8")
    removed = clear_derived_pages()
    assert sorted(removed) == sorted(pages)
    assert all(not page.exists() and (page.parent / "memo.md").is_file() for page in pages)


def test_a_folder_that_only_held_the_untouched_page_goes(family, fork):
    _parent, _child, agent = family
    page = _earlier_page(fork, agent)
    clear_derived_pages()
    assert not page.parent.exists()


def test_a_page_the_fork_wrote_itself_stays_with_its_other_pages(family, fork):
    _parent, _child, agent = family
    page = _earlier_page(fork, agent)
    page.write_text("<p>the fork's own words</p>", encoding="utf-8")
    (page.parent / "notes.html").write_text("<p>x</p>", encoding="utf-8")
    assert clear_derived_pages() == []
    assert sorted(path.name for path in page.parent.iterdir()) == ["index.html", "notes.html"]


def test_a_fork_with_pages_of_its_own_keeps_the_top_page_that_leads_to_them(family, fork):
    # 意図: 自分のページを持つ fork の手つかずのトップページを消すと、 目次からそのページへ辿れなくなる
    _parent, _child, agent = family
    page = _earlier_page(fork, agent)
    (page.parent / "findings.html").write_text("<p>x</p>", encoding="utf-8")
    assert clear_derived_pages() == []
    assert page.is_file()


def test_the_page_of_a_tab_that_comes_from_no_other_tab_stays_untouched(family):
    parent, _child, agent = family
    page = _earlier_page(parent, agent)
    assert clear_derived_pages() == []
    assert page.is_file()
