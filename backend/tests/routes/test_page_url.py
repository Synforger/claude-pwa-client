"""Tests of `GET /page-url` (= `backend/routes/page_url.py`): the tailnet URL of a page, and why there is none."""

from __future__ import annotations

import pytest

from backend.page_url.page_url_refusal import PageUrlRefusal

PAGE_PORT = 8799
SERVED = {"TCP": {str(PAGE_PORT): {"HTTPS": True}},
          "Web": {f"mac.tailnet.ts.net:{PAGE_PORT}": {"Handlers": {"/": {"Proxy": f"http://127.0.0.1:{PAGE_PORT}"}}}}}


def modules():
    """The routes, imported when a test runs: the app reads the configuration's agents when it is first imported, and
    the test session puts its own configuration in place only after collection."""
    import backend.routes.files as files_mod  # noqa: PLC0415
    import backend.routes.page_url as page_url_routes  # noqa: PLC0415
    return files_mod, page_url_routes


@pytest.fixture
def pages(tmp_path, monkeypatch):
    """A page origin folder with one page, served on the tailnet; the listener is open."""
    files_mod, page_url_routes = modules()
    folder = (tmp_path / "agents").resolve()
    (folder / "agent/pages").mkdir(parents=True)
    (folder / "agent/pages/report.html").write_text("<p>hi</p>", encoding="utf-8")
    # the endpoint's own reading of the configuration (= the configuration file itself stays the test session's)
    monkeypatch.setattr(page_url_routes, "page_origin", lambda: (folder, PAGE_PORT))
    monkeypatch.setattr(files_mod, "page_listening", True)
    monkeypatch.setattr(page_url_routes, "serve_status", lambda: SERVED)
    return folder


def asked(path: str):
    from fastapi.testclient import TestClient  # noqa: PLC0415
    from backend.main import app  # noqa: PLC0415
    return TestClient(app).get("/page-url", params={"path": path})


def code_of(response) -> str:
    return response.json()["detail"]["code"]


def test_a_page_in_the_folder_gets_its_tailnet_url(pages):
    response = asked(str(pages / "agent/pages/report.html"))
    assert response.status_code == 200
    assert response.json() == {"url": f"https://mac.tailnet.ts.net:{PAGE_PORT}/agent/pages/report.html"}


def test_a_path_through_a_link_is_answered_by_where_the_file_really_is(pages, tmp_path):
    (tmp_path / "link").symlink_to(pages / "agent")
    assert asked(str(tmp_path / "link/pages/report.html")).json()["url"].endswith("/agent/pages/report.html")


def test_a_file_outside_the_folder_is_refused_before_the_tailnet_is_asked(pages, tmp_path, monkeypatch):
    def serve_status():
        raise PageUrlRefusal("page_tailnet_unavailable", "no tailscale")
    monkeypatch.setattr(modules()[1], "serve_status", serve_status)
    (tmp_path / "other.html").write_text("x", encoding="utf-8")
    response = asked(str(tmp_path / "other.html"))
    assert (response.status_code, code_of(response)) == (400, "page_outside_origin")


@pytest.mark.parametrize("path, status, code", [
    ("agent/pages/report.html", 400, "page_path_not_absolute"),
    ("/no/such/page.html", 404, "page_not_found"),
])
def test_a_path_that_names_no_file_is_refused(pages, path, status, code):
    response = asked(path)
    assert (response.status_code, code_of(response)) == (status, code)


def test_without_a_page_origin_it_is_refused(pages, monkeypatch):
    monkeypatch.setattr(modules()[1], "page_origin", lambda: None)
    response = asked(str(pages / "agent/pages/report.html"))
    assert (response.status_code, code_of(response)) == (409, "page_origin_unset")


def test_while_the_page_listener_is_closed_it_is_refused(pages, monkeypatch):
    monkeypatch.setattr(modules()[0], "page_listening", False)
    response = asked(str(pages / "agent/pages/report.html"))
    assert (response.status_code, code_of(response)) == (503, "page_origin_not_listening")


@pytest.mark.parametrize("answer, status, code", [
    ({}, 409, "page_not_on_tailnet"),
    (PageUrlRefusal("page_tailnet_unavailable", "no tailscale"), 503, "page_tailnet_unavailable"),
])
def test_a_tailnet_that_does_not_serve_the_page_port_is_refused(pages, monkeypatch, answer, status, code):
    def serve_status():
        if isinstance(answer, Exception):
            raise answer
        return answer
    monkeypatch.setattr(modules()[1], "serve_status", serve_status)
    response = asked(str(pages / "agent/pages/report.html"))
    assert (response.status_code, code_of(response)) == (status, code)
