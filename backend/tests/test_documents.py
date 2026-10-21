"""資料を開ける形にする module (= backend/documents/) の unit test。

変換の command を呼ぶ所は、 呼び方 (= shell を通さず、 path を 1 つの引数で渡す) を偽の runner で確かめ、 実際の
変換は道具が在る機械でだけ小さな pdf・docx を作って通す。 控え (= store) は偽の変換で、 作り直さない・変わったら
作り直す・上限で消す・失敗を覚える、 を確かめる。
"""
import json
import shutil
import subprocess
import threading
import time
import zipfile
from pathlib import Path

import pytest

from backend.documents import convert, markdown, pages, store as store_mod, strings
from backend.documents.convert import ConversionError
from backend.documents.store import DocumentStore


# --- 試験用の資料 ---

def make_pdf(path: Path, page_count: int = 1) -> Path:
    """n 頁の最小の pdf (= xref を正しく書く。 道具が読み直しを要さない形)。"""
    objects = [b"<< /Type /Catalog /Pages 2 0 R >>"]
    kids = " ".join(f"{3 + 2 * i} 0 R" for i in range(page_count))
    objects.append(f"<< /Type /Pages /Kids [{kids}] /Count {page_count} >>".encode())
    for i in range(page_count):
        content = 4 + 2 * i
        objects.append(
            f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 200 100] /Contents {content} 0 R "
            f"/Resources << /Font << /F1 << /Type /Font /Subtype /Type1 /BaseFont /Helvetica >> >> >> >>".encode()
        )
        stream = f"BT /F1 24 Tf 20 40 Td (page {i + 1}) Tj ET".encode()
        objects.append(b"<< /Length %d >>\nstream\n" % len(stream) + stream + b"\nendstream")
    out, offsets = bytearray(b"%PDF-1.4\n"), []
    for n, body in enumerate(objects, 1):
        offsets.append(len(out))
        out += b"%d 0 obj\n" % n + body + b"\nendobj\n"
    xref = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objects) + 1)
    for offset in offsets:
        out += b"%010d 00000 n \n" % offset
    out += b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (len(objects) + 1, xref)
    path.write_bytes(bytes(out))
    return path


def make_docx(path: Path, text: str = "Hello document") -> Path:
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("[Content_Types].xml",
                   '<?xml version="1.0"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
                   '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
                   '<Default Extension="xml" ContentType="application/xml"/>'
                   '<Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>'
                   "</Types>")
        z.writestr("_rels/.rels",
                   '<?xml version="1.0"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                   '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>'
                   "</Relationships>")
        z.writestr("word/document.xml",
                   '<?xml version="1.0"?><w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
                   f"<w:body><w:p><w:r><w:t>{text}</w:t></w:r></w:p></w:body></w:document>")
    return path


have_poppler = shutil.which("pdftoppm") is not None or Path("/opt/homebrew/bin/pdftoppm").exists()
have_soffice = shutil.which("soffice") is not None or Path("/opt/homebrew/bin/soffice").exists() \
    or Path("/Applications/LibreOffice.app/Contents/MacOS/soffice").exists()


# --- 拡張子 ---

@pytest.mark.parametrize("name,kind", [
    ("a.pdf", "pdf"), ("A.PDF", "pdf"), ("a.pptx", "office"), ("a.xlsx", "office"), ("a.docx", "office"),
    ("a.tif", "tiff"), ("a.TIFF", "tiff"), ("a.md", "markdown"), ("a.markdown", "markdown"),
    ("a.html", None), ("a.doc", None), ("a.txt", None), ("pdf", None),
])
def test_kind_of_names_what_the_viewer_can_open(name, kind):
    assert convert.kind_of(Path(name)) == kind


# --- 道具の呼び方 (= shell を通さない) ---

class FakeRun:
    """subprocess.run の代わり。 呼ばれた引数を溜め、 頁の画像だけ作る。"""

    def __init__(self, returncode=0, stderr=b"", on_call=None):
        self.calls = []
        self.returncode, self.stderr, self.on_call = returncode, stderr, on_call

    def __call__(self, args, **kwargs):
        self.calls.append((args, kwargs))
        if self.on_call:
            self.on_call(args)
        return subprocess.CompletedProcess(args, self.returncode, b"", self.stderr)


@pytest.fixture
def all_tools(monkeypatch):
    monkeypatch.setattr(convert, "_tool", lambda name: f"/bin/{name}")


def jpeg_bytes(width=10, height=20):
    """SOF を持つだけの最小の JPEG (= 大きさを読む所の試験用)。"""
    return (b"\xff\xd8" + b"\xff\xc0" + (17).to_bytes(2, "big") + b"\x08" + height.to_bytes(2, "big")
            + width.to_bytes(2, "big") + b"\x03" + b"\x00" * 9 + b"\xff\xd9")


def test_pdf_is_rendered_by_pdftoppm_with_the_path_as_one_argument_and_no_shell(tmp_path, all_tools, monkeypatch):
    # 意図: 名前に空白・; ・$( ) が在っても、 shell の構文として読まれず 1 つの引数で渡る
    source = tmp_path / "a b; $(touch pwned).pdf"
    source.write_bytes(b"%PDF-1.4")

    def render(args):
        shots = Path(args[-1]).parent
        (shots / "p-1.jpg").write_bytes(jpeg_bytes(30, 40))
        (shots / "p-2.jpg").write_bytes(jpeg_bytes(30, 40))

    run = FakeRun(on_call=render)
    monkeypatch.setattr(convert.subprocess, "run", run)
    out = tmp_path / "out"
    sizes = convert.render_pages(source, out)
    assert sizes == [(30, 40), (30, 40)]
    assert sorted(p.name for p in out.glob("p-*.jpg")) == ["p-001.jpg", "p-002.jpg"]
    args, kwargs = run.calls[0]
    assert isinstance(args, list) and args[0] == "/bin/pdftoppm"
    assert str(source) in args and kwargs.get("shell") in (None, False)
    assert kwargs["timeout"] == convert.COMMAND_TIMEOUT_SEC
    assert not (tmp_path / "pwned").exists()


def test_office_file_goes_through_soffice_then_pdftoppm(tmp_path, all_tools, monkeypatch):
    source = tmp_path / "deck.pptx"
    source.write_bytes(b"x")
    phases = []

    def call(args):
        if args[0].endswith("soffice"):
            out_dir = Path(args[args.index("--outdir") + 1])
            (out_dir / "deck.pdf").write_bytes(b"%PDF")
        else:
            (Path(args[-1]).parent / "p-1.jpg").write_bytes(jpeg_bytes())

    run = FakeRun(on_call=call)
    monkeypatch.setattr(convert.subprocess, "run", run)
    convert.render_pages(source, tmp_path / "out", phases.append)
    soffice, pdftoppm = (c[0] for c in run.calls)
    assert soffice[0] == "/bin/soffice" and "--headless" in soffice and "--convert-to" in soffice
    assert str(source) in soffice
    # 開いている LibreOffice とぶつからないよう、 呼ぶたびに別の設定の folder
    assert any(a.startswith("-env:UserInstallation=file://") for a in soffice)
    assert pdftoppm[0] == "/bin/pdftoppm"
    assert phases == ["office", "render"]


def test_a_missing_tool_is_reported_by_name(tmp_path, monkeypatch):
    monkeypatch.setattr(convert, "_tool", lambda name: None)
    source = tmp_path / "a.docx"
    source.write_bytes(b"x")
    with pytest.raises(ConversionError) as error:
        convert.render_pages(source, tmp_path / "out")
    assert error.value.code == "missing_tool" and error.value.params == {"tool": "soffice"}


def test_a_command_that_runs_too_long_is_stopped_and_reported(tmp_path, all_tools, monkeypatch):
    def hang(args, **kwargs):
        raise subprocess.TimeoutExpired(args, kwargs["timeout"])

    monkeypatch.setattr(convert.subprocess, "run", hang)
    source = tmp_path / "a.pdf"
    source.write_bytes(b"x")
    with pytest.raises(ConversionError) as error:
        convert.render_pages(source, tmp_path / "out")
    assert error.value.code == "timeout" and error.value.params == {"s": convert.COMMAND_TIMEOUT_SEC}


@pytest.mark.parametrize("stderr,code", [
    (b"Command Line Error: Incorrect password", "protected"),
    (b"Syntax Error: Couldn't read xref table", "unreadable"),
])
def test_a_failed_command_becomes_a_one_line_reason(tmp_path, all_tools, monkeypatch, stderr, code):
    monkeypatch.setattr(convert.subprocess, "run", FakeRun(returncode=1, stderr=stderr))
    source = tmp_path / "a.pdf"
    source.write_bytes(b"x")
    with pytest.raises(ConversionError) as error:
        convert.render_pages(source, tmp_path / "out")
    assert error.value.code == code


def test_a_run_that_makes_no_page_is_reported(tmp_path, all_tools, monkeypatch):
    monkeypatch.setattr(convert.subprocess, "run", FakeRun())
    source = tmp_path / "a.pdf"
    source.write_bytes(b"x")
    with pytest.raises(ConversionError) as error:
        convert.render_pages(source, tmp_path / "out")
    assert error.value.code == "no_pages"


def test_tiff_uses_tiff2pdf_and_falls_back_to_the_first_page_with_sips(tmp_path, all_tools, monkeypatch):
    source = tmp_path / "scan.tif"
    source.write_bytes(b"II*\x00")

    def call(args):
        if args[0].endswith("tiff2pdf"):
            raise AssertionError("never reaches here")
        if args[0].endswith("sips"):
            Path(args[args.index("--out") + 1]).write_bytes(jpeg_bytes(7, 9))

    def run(args, **kwargs):
        if args[0].endswith("tiff2pdf"):
            return subprocess.CompletedProcess(args, 1, b"", b"tiff2pdf: unsupported")
        call(args)
        return subprocess.CompletedProcess(args, 0, b"", b"")

    monkeypatch.setattr(convert.subprocess, "run", run)
    assert convert.render_pages(source, tmp_path / "out") == [(7, 9)]


def test_jpeg_size_reads_the_frame_header(tmp_path):
    path = tmp_path / "a.jpg"
    path.write_bytes(jpeg_bytes(123, 45))
    assert convert.jpeg_size(path) == (123, 45)
    path.write_bytes(b"not a jpeg")
    with pytest.raises(ConversionError):
        convert.jpeg_size(path)


# --- 実物の道具を通す (= 道具が在る機械でだけ) ---

@pytest.mark.skipif(not have_poppler, reason="poppler is not installed")
def test_a_real_pdf_becomes_one_image_per_page_in_order(tmp_path):
    source = make_pdf(tmp_path / "two.pdf", page_count=2)
    sizes = convert.render_pages(source, tmp_path / "out")
    assert len(sizes) == 2
    # 200 x 100 pt を 130 dpi で描く (= 端の 1 px は道具の丸めに任せる)
    assert abs(sizes[0][0] - 200 / 72 * convert.DPI) <= 1 and abs(sizes[0][1] - 100 / 72 * convert.DPI) <= 1
    assert [p.name for p in sorted((tmp_path / "out").glob("p-*.jpg"))] == ["p-001.jpg", "p-002.jpg"]


@pytest.mark.skipif(not (have_poppler and have_soffice), reason="LibreOffice or poppler is not installed")
def test_a_real_docx_becomes_page_images(tmp_path):
    source = make_docx(tmp_path / "memo.docx")
    sizes = convert.render_pages(source, tmp_path / "out")
    assert len(sizes) == 1 and sizes[0][0] > 500
    assert (tmp_path / "out" / "p-001.jpg").read_bytes()[:2] == b"\xff\xd8"


@pytest.mark.skipif(not have_poppler, reason="poppler is not installed")
def test_a_broken_pdf_is_reported_as_unreadable(tmp_path):
    source = tmp_path / "broken.pdf"
    source.write_bytes(b"this is not a pdf")
    with pytest.raises(ConversionError) as error:
        convert.render_pages(source, tmp_path / "out")
    assert error.value.code == "unreadable"


# --- 控え ---

class InlineExecutor:
    """submit した仕事をその場で走らせる (= thread を待たずに store の振る舞いを確かめる)。"""

    def submit(self, fn, *args):
        fn(*args)


@pytest.fixture
def fake_render(monkeypatch):
    """convert.render_pages の代わり。 呼んだ回数を数え、 頁の画像を `pages` 枚作る。"""
    state = {"calls": 0, "pages": 2, "error": None, "gate": None}

    def render(source, out_dir, on_phase=lambda phase: None):
        state["calls"] += 1
        on_phase("render")
        if state["gate"] is not None:
            assert state["gate"].wait(5)
        if state["error"] is not None:
            raise state["error"]
        out_dir.mkdir(parents=True, exist_ok=True)
        for n in range(1, state["pages"] + 1):
            (out_dir / f"p-{n:03d}.jpg").write_bytes(jpeg_bytes() + b"\x00" * 1000)
        return [(10, 20)] * state["pages"]

    monkeypatch.setattr(convert, "render_pages", render)
    return state


def inline_store(tmp_path, max_bytes=1 << 30):
    return DocumentStore(tmp_path / "cache", max_bytes, executor=InlineExecutor())


def doc(tmp_path, name="a.pdf", body=b"%PDF-1.4"):
    path = tmp_path / "docs" / name
    path.parent.mkdir(exist_ok=True)
    path.write_bytes(body)
    return path


def test_the_second_open_uses_the_kept_pages(tmp_path, fake_render):
    store, source = inline_store(tmp_path), doc(tmp_path)
    assert store.status(source).state == "running"  # 同期の実行器では、 最初の応えは作り始めた直後
    first = store.status(source)
    assert first.state == "ready" and len(first.entry.pages) == 2
    assert store.status(source).entry.key == first.entry.key
    assert fake_render["calls"] == 1


def test_a_changed_file_is_converted_again_and_the_old_pages_go(tmp_path, fake_render):
    store, source = inline_store(tmp_path), doc(tmp_path)
    store.status(source)
    old = store.status(source).entry
    source.write_bytes(b"%PDF-1.4 changed")
    store.status(source)
    new = store.status(source).entry
    assert new.key != old.key and fake_render["calls"] == 2
    assert not old.directory.exists()  # 同じ file の古い控えは、 新しい控えができた時に消える


def test_the_same_size_and_time_but_another_path_is_another_entry(tmp_path, fake_render):
    store = inline_store(tmp_path)
    a, b = doc(tmp_path, "a.pdf"), doc(tmp_path, "b.pdf")
    store.status(a), store.status(b)
    assert store.status(a).entry.key != store.status(b).entry.key


def test_the_cache_keeps_to_its_limit_by_dropping_the_longest_unopened(tmp_path, fake_render):
    fake_render["pages"] = 1
    store = inline_store(tmp_path, max_bytes=2500)  # 1 file が約 1 KB
    files = [doc(tmp_path, f"{n}.pdf") for n in range(3)]
    for source in files[:2]:
        store.status(source)
    now = time.time()
    # 0 番を古く、 1 番を新しく開いたことにして、 2 番を作る
    for source, age in ((files[0], 100), (files[1], 10)):
        meta = store.cache_dir / store_mod.cache_key(source) / "meta.json"
        import os  # noqa: PLC0415
        os.utime(meta, (now - age, now - age))
    store.status(files[2])
    kept = {store_mod.cache_key(f): (store.cache_dir / store_mod.cache_key(f)).exists() for f in files}
    assert list(kept.values()) == [False, True, True]


def test_opening_a_kept_file_moves_it_to_the_newest(tmp_path, fake_render):
    store, source = inline_store(tmp_path), doc(tmp_path)
    store.status(source)
    meta = store.cache_dir / store_mod.cache_key(source) / "meta.json"
    import os  # noqa: PLC0415
    os.utime(meta, (1, 1))
    store.status(source)
    assert meta.stat().st_mtime > 1000


def test_a_failure_is_remembered_and_tried_again_on_request(tmp_path, fake_render):
    store, source = inline_store(tmp_path), doc(tmp_path)
    fake_render["error"] = ConversionError("unreadable")
    store.status(source)
    failed = store.status(source)
    assert failed.state == "failed" and failed.error.code == "unreadable"
    assert store.status(source).state == "failed" and fake_render["calls"] == 1  # 開くたびに作り直さない
    fake_render["error"] = None
    store.status(source, retry=True)
    assert store.status(source).state == "ready" and fake_render["calls"] == 2


def test_an_unexpected_error_is_a_failure_not_a_crash(tmp_path, fake_render):
    store, source = inline_store(tmp_path), doc(tmp_path)
    fake_render["error"] = RuntimeError("boom")
    store.status(source)
    assert store.status(source).error.code == "failed"
    assert not list((tmp_path / "cache").glob(".work-*"))  # 作業の folder は残らない


def test_requests_while_converting_share_one_conversion(tmp_path, fake_render):
    fake_render["gate"] = threading.Event()
    store = DocumentStore(tmp_path / "cache", 1 << 30)
    source = doc(tmp_path)
    try:
        states = [store.status(source) for _ in range(3)]
        assert all(s.state == "running" and s.phase in ("start", "render") for s in states)
        fake_render["gate"].set()
        deadline = time.time() + 5
        while store.status(source).state != "ready":
            assert time.time() < deadline
            time.sleep(0.01)
        assert fake_render["calls"] == 1
    finally:
        fake_render["gate"].set()


def test_a_half_made_entry_is_not_used(tmp_path, fake_render):
    store, source = inline_store(tmp_path), doc(tmp_path)
    store.status(source)
    entry = store.status(source).entry
    entry.image(2).unlink()
    assert store.status(source).state == "running"  # 欠けた控えは使わず、 作り直す


def test_leftover_work_folders_are_cleaned_when_old(tmp_path):
    cache = tmp_path / "cache"
    old, new = cache / ".work-old", cache / ".work-new"
    old.mkdir(parents=True), new.mkdir()
    import os  # noqa: PLC0415
    os.utime(old, (1, 1))
    DocumentStore(cache, 1 << 30, executor=InlineExecutor())
    assert not old.exists() and new.exists()  # 新しい物は別の process が作業中かもしれない


def test_the_key_follows_path_size_and_time(tmp_path):
    source = doc(tmp_path)
    key = store_mod.cache_key(source)
    assert store_mod.cache_key(source) == key
    source.write_bytes(b"%PDF-1.4 more")
    assert store_mod.cache_key(source) != key


# --- 頁の HTML ---

def test_pages_escape_names_and_say_why_a_file_failed():
    page = pages.failed('<b>x</b>.pdf', "~/x", ConversionError("missing_tool", tool="soffice"), "en")
    assert "<b>x</b>" not in page and "&lt;b&gt;x&lt;/b&gt;.pdf" in page
    assert "soffice is not installed" in page and 'href="?retry=1"' in page
    ja = pages.failed("a.pdf", "~/a.pdf", ConversionError("timeout", s=300), "ja")
    assert "300 秒" in ja


def test_the_waiting_page_refreshes_itself_without_scripts_and_never_keeps_a_retry():
    page = pages.waiting("a b.pdf", "a%20b.pdf", "~/a b.pdf", "office", 12.4, "en")
    assert 'http-equiv="refresh" content="2;url=a%20b.pdf"' in page
    assert "<script" not in page and "Converting to PDF (12 s)" in page


def test_the_ready_page_stacks_every_page_at_its_own_size():
    page = pages.ready("a.pdf", "a.pdf", "~/a.pdf", "abc123", [(100, 50), (100, 60)], "en")
    assert 'src="a.pdf?page=1&amp;v=abc123" width="100" height="50"' in page
    assert 'src="a.pdf?page=2&amp;v=abc123" width="100" height="60"' in page
    assert 'id="p2"' in page and "2 pages" in page


def test_language_follows_the_first_accept_language():
    assert strings.pick_language("ja,en;q=0.8") == "ja"
    assert strings.pick_language("en-US,ja;q=0.5") == "en"
    assert strings.pick_language(None) == "en"
    assert set(strings._STRINGS["ja"]) == set(strings._STRINGS["en"])


# --- Markdown ---

def render_md(tmp_path, text, own="doc.md", files=()):
    for name, body in files:
        target = tmp_path / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(body) if isinstance(body, str) else target.write_bytes(body)
    neighbors = markdown.Neighbors(
        tmp_path, lambda p: p.is_file(), lambda p: p.read_text() if p.is_file() else None,
    )
    return markdown.render(text, neighbors, own, "en")


def test_headings_get_github_style_ids_and_duplicates_are_numbered(tmp_path):
    html, title = render_md(tmp_path, "# Top Title\n\n## 1. 背景 (v2)\n\n## Notes\n\n## Notes\n")
    assert title == "Top Title"
    assert '<h1 id="top-title">' in html and '<h2 id="1-背景-v2">' in html
    assert '<h2 id="notes">' in html and '<h2 id="notes-1">' in html


def test_a_contents_link_whose_words_do_not_match_goes_to_the_heading_that_holds_them_in_order(tmp_path):
    html, _ = render_md(tmp_path, "[背景](#背景) [範囲](#scope)\n\n## 1. 背景と目的\n\n## 2. 範囲 (v2)\n")
    assert 'href="#1-%E8%83%8C%E6%99%AF%E3%81%A8%E7%9B%AE%E7%9A%84"' in html
    # 語が見出しに入っていない目次は、 張り直さずそのまま
    assert 'href="#scope"' in html


def test_an_exact_link_is_left_alone(tmp_path):
    html, _ = render_md(tmp_path, "[x](#notes)\n\n## Notes\n\n## Notes extended\n")
    assert 'href="#notes"' in html


def test_a_link_into_another_markdown_is_fixed_against_that_files_headings(tmp_path):
    other = "# 概要\n\n## 1. 背景と目的\n\n## 2. 範囲 (v2)\n"
    html, _ = render_md(
        tmp_path, "[背景](other.md#背景) [範囲](sub/other.md#範囲)\n",
        files=[("other.md", other), ("sub/other.md", "## 0. はじめに\n\n## 範囲の定義\n")],
    )
    assert 'href="other.md#1-%E8%83%8C%E6%99%AF%E3%81%A8%E7%9B%AE%E7%9A%84"' in html
    assert 'href="sub/other.md#%E7%AF%84%E5%9B%B2%E3%81%AE%E5%AE%9A%E7%BE%A9"' in html


def test_a_link_to_the_same_file_by_name_uses_its_own_headings(tmp_path):
    html, _ = render_md(tmp_path, "[b](./doc.md#背景)\n\n## 1. 背景\n")
    assert 'href="./doc.md#1-%E8%83%8C%E6%99%AF"' in html


def test_a_link_into_a_file_that_is_not_there_or_not_markdown_keeps_its_fragment(tmp_path):
    html, _ = render_md(tmp_path, "[a](gone.md#x) [b](data.pdf#page=2) [c](https://example.com/x#y)\n", files=[("data.pdf", b"x")])
    assert 'href="gone.md#x"' in html and 'href="data.pdf#page=2"' in html
    assert 'href="https://example.com/x#y" rel="noreferrer"' in html


def test_a_figure_that_is_not_there_says_so_instead_of_breaking(tmp_path):
    html, _ = render_md(tmp_path, "![ok](fig/a.png) ![ng](fig/gone.png)\n", files=[("fig/a.png", b"x")])
    assert '<img src="fig/a.png" alt="ok" loading="lazy"' in html
    assert 'class="missing">Image not found: <code>fig/gone.png</code>' in html
    assert 'src="fig/gone.png"' not in html


def test_an_external_image_is_shown_as_not_loaded(tmp_path):
    html, _ = render_md(tmp_path, "![x](https://example.com/a.png) ![d](data:image/png;base64,AAAA)\n")
    assert "External image, not loaded:" in html and '<a href="https://example.com/a.png">' in html
    assert '<img src="data:image/png;base64,AAAA"' in html


def test_written_html_is_shown_as_text_and_unsafe_links_stay_text(tmp_path):
    html, _ = render_md(tmp_path, "<script>alert(1)</script>\n\n[x](javascript:alert(1))\n\n<br>\n")
    assert "<script>" not in html and "&lt;script&gt;" in html
    assert "<a " not in html  # javascript: の行き先は、 リンクにならず文字のまま


def test_br_in_a_table_cell_breaks_the_line_and_tables_scroll(tmp_path):
    html, _ = render_md(tmp_path, "| a | b |\n|---|---|\n| x<br>y | 1 |\n")
    assert '<div class="tablewrap"><table>' in html and "x<br>y" in html


def test_front_matter_is_shown_as_a_block(tmp_path):
    html, _ = render_md(tmp_path, "---\ntitle: T\nupdated: 2026-01-01\n---\n\n# Body\n")
    assert '<pre class="front-matter"><code>title: T\nupdated: 2026-01-01</code></pre>' in html
    assert '<h1 id="body">' in html


def test_fix_anchor_picks_the_first_heading_that_holds_the_words_in_order():
    slugs = ["intro", "1-背景と目的", "5-背景知識"]
    assert markdown.fix_anchor("背景", slugs) == "1-背景と目的"
    assert markdown.fix_anchor("intro", slugs) == "intro"
    assert markdown.fix_anchor("zzz", slugs) == "zzz"
    assert markdown.fix_anchor("", slugs) == ""
