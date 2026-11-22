"""Which files the page origin serves when the configuration lists folders."""

from __future__ import annotations

import pytest

from backend._common.page_folders import folder_list_problem, is_served

TIERS = ("*/pages", "*/projects/**/pages", "agent/projects/sample/research/explainer")


@pytest.mark.parametrize("path", [
    "agent/pages/tab/index.html",
    "agent/pages/_common/toc.js",
    "agent/projects/sample/pages/tab/branch/guide.html",
    "agent/projects/sample/subprojects/tool/subprojects/part/pages/tab/index.html",
    "agent/projects/sample/research/explainer/index.html",
    "agent/projects/sample/research/explainer/data/layout.json",
])
def test_a_file_in_a_listed_folder_or_below_is_served(path: str) -> None:
    assert is_served(path, TIERS)


@pytest.mark.parametrize("path", [
    "agent/rules/always.md",
    "agent/index.html",
    "pages",
    "agent/pages",
    "agent/pages-old/index.html",
    "agent/projects/sample/research/notes.html",
    "agent/projects/sample/research/explainer-old/index.html",
    "agent/_scratch/pages/index.html",
    "agent/projects/_template/pages/index.html",
    "agent/projects/sample/_scratch/copy/pages/index.html",
    "agent/projects/sample/.hidden/pages/index.html",
    ".agent/pages/index.html",
    "_agent/pages/index.html",
])
def test_a_file_outside_the_list_is_not_served(path: str) -> None:
    assert not is_served(path, TIERS)


def test_without_a_list_every_file_of_the_folder_is_served() -> None:
    assert is_served("agent/rules/always.md", None)


def test_an_empty_list_serves_nothing() -> None:
    assert not is_served("agent/pages/index.html", ())


def test_a_name_that_starts_with_an_underscore_is_served_when_the_list_names_it() -> None:
    assert is_served("agent/_scratch/shots/a.png", ("agent/_scratch/shots",))


def test_a_name_is_the_same_in_either_unicode_form() -> None:
    composed, decomposed = "agent/プロ", "agent/プロ"
    assert is_served(f"{decomposed}/index.html", (composed,))
    assert is_served(f"{composed}/index.html", (decomposed,))


def test_a_path_of_many_folders_is_judged() -> None:
    assert not is_served("agent/projects/" + "x/" * 5000 + "index.html", TIERS)


@pytest.mark.parametrize("value, problem", [
    ("*/pages", "must be a list"),
    ([1], "must be a list"),
    ([""], "is not a folder"),
    (["/agent/pages"], "is not a folder"),
    (["agent/pages/"], "is not a folder"),
    (["agent//pages"], "is not a folder"),
    (["agent/../pages"], "is not a folder"),
    (["./pages"], "is not a folder"),
    (["**"], "is not a folder"),
    (["agent/**"], "is not a folder"),
    (["agent/page*"], "is not a folder"),
])
def test_a_mistake_in_the_list_is_named(value: object, problem: str) -> None:
    assert problem in (folder_list_problem(value) or "")


@pytest.mark.parametrize("value", [None, [], list(TIERS)])
def test_a_well_formed_list_has_no_problem(value: object) -> None:
    assert folder_list_problem(value) is None
