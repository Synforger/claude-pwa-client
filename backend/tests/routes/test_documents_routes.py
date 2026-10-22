"""資料の口 (= /file/open・/file/view・ページの origin が pdf・Office・tif を開く所) の test。

開ける範囲と検査は他の file と同じであること (= 新しく読める場所を広げない) と、 初めて開く時の待ち・失敗の画面、
ページの origin の HTML から資料へのリンクが開くことを確かめる。 変換そのものは偽
(= 変換の command を呼ぶ所は test_documents.py)。
"""
import json
import tempfile
import threading
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from backend.documents import convert
from backend.documents.convert import ConversionError

from backend.tests.documents.test_documents import jpeg_bytes

PAGE_PORT = 8798


def with_config(monkeypatch, cfg):
    import backend._common.config as config_mod  # noqa: PLC0415
    path = Path(tempfile.mkdtemp(prefix="cpc-documents-")) / "config.json"
    path.write_text(json.dumps(cfg))
    monkeypatch.setattr(config_mod, "CONFIG_PATH", path)
    config_mod.get_config.cache_clear()


@pytest.fixture
def fake_render(monkeypatch):
    state = {"calls": 0, "error": None, "gate": None, "pages": 2}

    def render(source, out_dir, on_phase=lambda phase: None):
        state["calls"] += 1
        on_phase("office")
        if state["gate"] is not None:
            assert state["gate"].wait(5)
        if state["error"] is not None:
            raise state["error"]
        out_dir.mkdir(parents=True, exist_ok=True)
        for n in range(1, state["pages"] + 1):
            (out_dir / f"p-{n:03d}.jpg").write_bytes(jpeg_bytes(30, 40) + bytes([n]))
        return [(30, 40)] * state["pages"]

    monkeypatch.setattr(convert, "render_pages", render)
    return state


@pytest.fixture
def view(tmp_path, monkeypatch, fake_render):
    """HOME を tmp_path にした app (= /file/open・/file/view)。 控えは tmp_path/cache。"""
    import backend.routes.files as files_mod  # noqa: PLC0415
    from backend.main import app  # noqa: PLC0415
    monkeypatch.setattr(files_mod, "HOME", tmp_path)
    with_config(monkeypatch, {"documents": {"cache_dir": str(tmp_path / "cache")}})
    return TestClient(app)


@pytest.fixture
def pages_app(tmp_path, monkeypatch, fake_render):
    """HOME を tmp_path にし、 tmp_path/pages をページの origin にした app。"""
    import backend.routes.files as files_mod  # noqa: PLC0415
    monkeypatch.setattr(files_mod, "HOME", tmp_path)
    monkeypatch.setattr(files_mod, "page_listening", True)
    (tmp_path / "pages").mkdir(exist_ok=True)
    with_config(monkeypatch, {
        "documents": {"cache_dir": str(tmp_path / "cache")},
        "page_origin": {"folder": str(tmp_path / "pages"), "port": PAGE_PORT},
    })
    return TestClient(files_mod.page_app)


def put(tmp_path, rel, body=b"x"):
    path = tmp_path / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body) if isinstance(body, str) else path.write_bytes(body)
    return path


def open_when_ready(client, url, **kwargs):
    """待ちの画面を抜けるまで開き直す (= 画面が <meta refresh> でしている事)。"""
    for _ in range(300):
        res = client.get(url, **kwargs)
        if 'http-equiv="refresh"' not in res.text:
            return res
        time.sleep(0.02)
    raise AssertionError("still converting: " + url)


# --- /file/open ---

@pytest.mark.parametrize("name", ["a.pdf", "a.pptx", "a.xlsx", "a.docx", "a.tif", "a.tiff", "A.PDF"])
def test_file_open_sends_a_document_to_the_view_of_its_path(view, tmp_path, name):
    source = put(tmp_path, f"docs/{name}")
    res = view.get("/file/open", params={"path": str(source)}, follow_redirects=False)
    assert res.status_code == 307
    assert res.headers["location"] == "view/" + str(source).lstrip("/")


def test_file_open_still_takes_only_pages_and_documents(view, tmp_path):
    for name in ("a.png", "a.doc", "a.txt"):
        assert view.get("/file/open", params={"path": str(put(tmp_path, name))}).status_code == 415
    assert view.get("/file/open", params={"path": str(tmp_path / "gone.pdf")}).status_code == 404


# --- 初めて開く時の待ちと、 頁の画像 ---

def test_a_document_waits_while_converting_then_shows_its_pages(view, tmp_path, fake_render):
    source = put(tmp_path, "docs/deck v1.pptx")
    url = "/file/view" + str(source)
    fake_render["gate"] = threading.Event()
    try:
        waiting = view.get(url, headers={"accept-language": "en"})
        assert waiting.status_code == 200
        assert waiting.headers["content-type"] == "text/html; charset=utf-8"
        assert 'http-equiv="refresh" content="2;url=deck%20v1.pptx"' in waiting.text
        assert "Converting" in waiting.text and "<script" not in waiting.text
        assert waiting.headers["cache-control"] == "no-store"
    finally:
        fake_render["gate"].set()
    ready = open_when_ready(view, url)
    assert ready.status_code == 200 and "2 pages" in ready.text
    # 元の場所は HOME からの path で出す (= 機械の絶対 path は画面に出さない)
    assert "~/docs/deck v1.pptx" in ready.text and str(tmp_path) not in ready.text
    key = ready.text.split("v=")[1].split('"')[0]
    image = view.get(url + f"?page=2&v={key}")
    assert image.status_code == 200 and image.headers["content-type"] == "image/jpeg"
    assert image.content.endswith(b"\x02")
    assert "immutable" in image.headers["cache-control"]
    assert fake_render["calls"] == 1
    view.get(url)
    assert fake_render["calls"] == 1  # 2 回目からは控え


def test_page_images_are_refused_for_another_version_or_a_page_that_is_not_there(view, tmp_path, fake_render):
    source = put(tmp_path, "docs/a.pdf")
    url = "/file/view" + str(source)
    key = open_when_ready(view, url).text.split("v=")[1].split('"')[0]
    for query in ("page=0", "page=3", "page=x", "page=-1"):
        assert view.get(f"{url}?{query}&v={key}").status_code == 404, query
    assert view.get(f"{url}?page=1&v={'0' * 32}").status_code == 404
    assert view.get(f"{url}?page=1").status_code == 404  # 版の指定が無い


def test_a_changed_file_is_shown_from_new_pages(view, tmp_path, fake_render):
    source = put(tmp_path, "docs/a.pdf", b"%PDF-1")
    url = "/file/view" + str(source)
    old = open_when_ready(view, url).text.split("v=")[1].split('"')[0]
    source.write_bytes(b"%PDF-1 changed")
    new = open_when_ready(view, url).text.split("v=")[1].split('"')[0]
    assert new != old and fake_render["calls"] == 2
    assert view.get(f"{url}?page=1&v={old}").status_code == 404  # 古い頁の画像は返さない


def test_a_failed_conversion_says_why_in_one_line_and_can_be_tried_again(view, tmp_path, fake_render):
    source = put(tmp_path, "docs/a.docx")
    url = "/file/view" + str(source)
    fake_render["error"] = ConversionError("missing_tool", tool="soffice")
    failed = open_when_ready(view, url, headers={"accept-language": "ja"})
    assert failed.status_code == 422
    assert "soffice が入っていません" in failed.text and 'href="?retry=1"' in failed.text
    assert view.get(url).status_code == 422 and fake_render["calls"] == 1
    fake_render["error"] = None
    assert view.get(url + "?retry=1").status_code == 200  # 作り直しが始まる
    assert open_when_ready(view, url).status_code == 200


# --- 開ける範囲は /file/view と同じ ---

def test_documents_keep_the_home_deny_list_size_and_existence_checks(view, tmp_path, monkeypatch):
    import backend.routes.files as files_mod  # noqa: PLC0415
    put(tmp_path, ".ssh/a.pdf")
    put(tmp_path, "secrets/a.docx")
    put(tmp_path, "docs/big.pdf", b"x" * 20)
    for blocked in ("/file/view" + str(tmp_path / ".ssh/a.pdf"), "/file/view" + str(tmp_path / "secrets/a.docx"),
                    "/file/view/etc/a.pdf", "/file/view" + str(tmp_path) + "/../../etc/a.md"):
        assert view.get(blocked).status_code in (403, 404), blocked
    assert view.get("/file/view" + str(tmp_path / ".ssh/a.pdf")).status_code == 403
    assert view.get("/file/open", params={"path": "/etc/a.pdf"}).status_code == 403
    assert view.get("/file/view" + str(tmp_path / "docs/gone.pdf")).status_code == 404
    monkeypatch.setattr(files_mod, "VIEW_SIZE_LIMIT", 10)
    assert view.get("/file/view" + str(tmp_path / "docs/big.pdf")).status_code == 413


def test_a_link_out_of_home_cannot_be_opened_as_a_document(view, tmp_path):
    outside = put(tmp_path.parent, f"{tmp_path.name}-outside/a.pdf")
    inside = tmp_path / "docs"
    inside.mkdir()
    (inside / "link.pdf").symlink_to(outside)
    assert view.get("/file/view" + str(inside / "link.pdf")).status_code == 403


# --- ページの origin: HTML のページから資料へのリンク ---

def test_a_page_in_the_folder_can_link_to_a_document_and_it_opens_on_the_pages_port(pages_app, tmp_path):
    put(tmp_path, "pages/proj/index.html", '<a href="../materials/spec.pdf">spec</a>')
    put(tmp_path, "pages/materials/spec.pdf", b"%PDF-1")
    assert pages_app.get("/proj/index.html").status_code == 200
    # リンクを辿った先 (= 相対 URL を解いた path)
    res = open_when_ready(pages_app, "/materials/spec.pdf")
    assert res.status_code == 200 and 'src="spec.pdf?page=1&amp;v=' in res.text
    csp = res.headers["content-security-policy"]
    assert "allow-same-origin" in csp and "allow-top-navigation" not in csp and "frame-ancestors" in csp and f"connect-src http://testserver:{PAGE_PORT}/.store/" in csp
    key = res.text.split("v=")[1].split('"')[0]
    assert pages_app.get(f"/materials/spec.pdf?page=1&v={key}").headers["content-type"] == "image/jpeg"


def test_documents_on_the_pages_port_stay_inside_the_folder_and_the_deny_list(pages_app, tmp_path):
    put(tmp_path, "outside.pdf")
    put(tmp_path, "pages/.ssh/a.pdf")
    (tmp_path / "pages" / "link.pdf").symlink_to(tmp_path / "outside.pdf")
    assert pages_app.get("/../outside.pdf").status_code in (403, 404)
    assert pages_app.get("/%2E%2E/outside.pdf").status_code in (403, 404)
    assert pages_app.get("/link.pdf").status_code == 403
    assert pages_app.get("/.ssh/a.pdf").status_code == 403
    assert pages_app.get("/proj/gone.pdf").status_code == 404


def test_file_open_sends_a_document_in_the_folder_to_the_pages_port(pages_app, tmp_path):
    from backend.main import app  # noqa: PLC0415
    put(tmp_path, "pages/proj/spec.pdf")
    res = TestClient(app).get("/file/open", params={"path": str(tmp_path / "pages/proj/spec.pdf")}, follow_redirects=False)
    assert res.status_code == 307
    assert res.headers["location"] == f"http://testserver:{PAGE_PORT}/proj/spec.pdf"


# --- 設定 ---

def test_documents_settings_default_to_the_document_cache_dir_and_report_mistakes(monkeypatch):
    import backend._common.config as config_mod  # noqa: PLC0415
    from backend._common.paths import DOCUMENT_CACHE_DIR  # noqa: PLC0415
    with_config(monkeypatch, {})
    assert config_mod.documents_settings() == (DOCUMENT_CACHE_DIR, config_mod.DOCUMENTS_CACHE_MAX_MB_DEFAULT * 1024 * 1024)
    with_config(monkeypatch, {"documents": {"cache_dir": "~/kept", "cache_max_mb": 0.5}})
    folder, limit = config_mod.documents_settings()
    assert folder == Path("~/kept").expanduser().resolve() and limit == 512 * 1024
    for raw, problem in [
        ("x", "must be an object"),
        ({"cache_dir": 3}, "cache_dir must be a path"),
        ({"cache_max_mb": 0}, "cache_max_mb must be a positive number"),
        ({"cache_max_mb": True}, "cache_max_mb must be a positive number"),
    ]:
        with_config(monkeypatch, {"documents": raw})
        value, problems = config_mod._scan_documents()
        assert len(problems) == 1 and problem in problems[0]
        assert value == (DOCUMENT_CACHE_DIR, config_mod.DOCUMENTS_CACHE_MAX_MB_DEFAULT * 1024 * 1024)
