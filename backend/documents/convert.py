"""pdf・Office・tif を、 頁ごとの JPEG (= `p-001.jpg` …) にする。

外部の command (= LibreOffice の `soffice`・poppler の `pdftoppm`・libtiff の `tiff2pdf`) を呼ぶ。 file の path は
引数の配列で渡し、 shell は通さない (= 名前に空白や記号が在っても、 shell の構文として読まれない)。 失敗は
`ConversionError` (= 画面に出す理由の種類) で返す。
"""
from __future__ import annotations

import logging
import os
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Callable

logger = logging.getLogger(__name__)

PDF_SUFFIXES = frozenset({".pdf"})
OFFICE_SUFFIXES = frozenset({".pptx", ".xlsx", ".docx"})
TIFF_SUFFIXES = frozenset({".tif", ".tiff"})

# 頁の画像: A4 で幅 1075 px (= スマホで拡大しても表の数字が読める所)
DPI = 130
JPEG_QUALITY = 80
# tif は頁の大きさが読めない物が在る (= 解像度の印が無いと、 画素数がそのまま pt になる)。 長辺をそろえる
TIFF_LONG_SIDE_PX = 1520
# 1 つの command に待つ上限 (秒)。 超えたら止めて「時間切れ」 と画面に出す
COMMAND_TIMEOUT_SEC = 300

# launchd 等の短い PATH から起動された時でも、 道具を探せる場所
_EXTRA_BIN_DIRS = (
    "/opt/homebrew/bin",
    "/usr/local/bin",
    "/Applications/LibreOffice.app/Contents/MacOS",
)


class ConversionError(Exception):
    """変換できなかった理由。 `code` は strings の `reason_<code>` と対 (= 画面は利用者の言語で出す)。"""

    def __init__(self, code: str, **params):
        super().__init__(code)
        self.code = code
        self.params = params


def kind_of(path: Path) -> str | None:
    """`pdf` / `office` / `tiff`。 資料として開けない拡張子は None。"""
    suffix = path.suffix.lower()
    if suffix in PDF_SUFFIXES:
        return "pdf"
    if suffix in OFFICE_SUFFIXES:
        return "office"
    if suffix in TIFF_SUFFIXES:
        return "tiff"
    return None


def _tool(name: str) -> str | None:
    found = shutil.which(name)
    if found:
        return found
    for folder in _EXTRA_BIN_DIRS:
        candidate = Path(folder) / name
        if candidate.is_file() and os.access(candidate, os.X_OK):
            return str(candidate)
    return None


def _run(tool: str, args: list[str], timeout: float = COMMAND_TIMEOUT_SEC) -> subprocess.CompletedProcess:
    exe = _tool(tool)
    if exe is None:
        raise ConversionError("missing_tool", tool=tool)
    try:
        done = subprocess.run(
            [exe, *args], capture_output=True, stdin=subprocess.DEVNULL, timeout=timeout, check=False,
        )
    except subprocess.TimeoutExpired:
        raise ConversionError("timeout", s=int(timeout))
    except OSError:
        logger.exception("could not start %s", exe)
        raise ConversionError("failed")
    if done.returncode != 0:
        stderr = done.stderr.decode("utf-8", "replace").strip()
        logger.warning("%s exited %d: %s", tool, done.returncode, stderr[-500:])
        if "password" in stderr.lower():
            raise ConversionError("protected")
        raise ConversionError("unreadable")
    return done


def _office_to_pdf(source: Path, work: Path) -> Path:
    """LibreOffice で pdf にする。 設定の folder を毎回別にして、 開いている LibreOffice とぶつからないようにする。"""
    out_dir = work / "pdf"
    out_dir.mkdir()
    with tempfile.TemporaryDirectory(prefix="cpc-soffice-") as profile:
        _run("soffice", [
            f"-env:UserInstallation={Path(profile).as_uri()}",
            "--headless", "--norestore", "--convert-to", "pdf", "--outdir", str(out_dir), str(source),
        ])
    made = sorted(out_dir.glob("*.pdf"))
    if not made:
        raise ConversionError("unreadable")
    return made[0]


def _pdf_to_images(pdf: Path, out_dir: Path, work: Path, scale: list[str]) -> None:
    """pdftoppm は桁数を頁数に合わせて書くので、 3 桁に揃えて並び順を固定する。"""
    shots = work / "shots"
    shots.mkdir()
    _run("pdftoppm", [*scale, "-jpeg", "-jpegopt", f"quality={JPEG_QUALITY}", str(pdf), str(shots / "p")])
    for jpg in shots.glob("p-*.jpg"):
        shutil.move(str(jpg), out_dir / f"p-{int(jpg.stem.split('-')[1]):03d}.jpg")


def _tiff_to_images(source: Path, out_dir: Path, work: Path, on_phase: Callable[[str], None]) -> None:
    """tiff2pdf で頁をそろえて pdf にし、 pdf と同じに画像にする (= 複数頁の tif も全頁)。 道具が無い・読めない時は、
    macOS の sips で 1 頁目だけ画像にする。"""
    try:
        pdf = work / "tiff.pdf"
        _run("tiff2pdf", ["-o", str(pdf), str(source)])
        on_phase("render")
        _pdf_to_images(pdf, out_dir, work, ["-scale-to", str(TIFF_LONG_SIDE_PX)])
        return
    except ConversionError as error:
        if _tool("sips") is None:
            raise
        logger.info("tiff2pdf path failed (%s); using sips for the first page", error.code)
    for stale in out_dir.glob("p-*.jpg"):
        stale.unlink()
    _run("sips", [
        "-s", "format", "jpeg", "-s", "formatOptions", str(JPEG_QUALITY), str(source), "--out", str(out_dir / "p-001.jpg"),
    ])


def jpeg_size(path: Path) -> tuple[int, int]:
    """JPEG の幅と高さ (= SOF の印から読む)。 画像を読む前に枠の大きさを決め、 頁内リンクの着地をずらさないため。"""
    data = path.read_bytes()
    i = 2
    while i + 9 < len(data):
        if data[i] != 0xFF:
            i += 1
            continue
        marker = data[i + 1]
        if marker in (0xC0, 0xC1, 0xC2):
            return int.from_bytes(data[i + 7:i + 9], "big"), int.from_bytes(data[i + 5:i + 7], "big")
        i += 2 + int.from_bytes(data[i + 2:i + 4], "big")
    raise ConversionError("unreadable")


def render_pages(source: Path, out_dir: Path, on_phase: Callable[[str], None] = lambda phase: None) -> list[tuple[int, int]]:
    """`source` を `out_dir/p-001.jpg` … にして、 各頁の (幅, 高さ) を順に返す。

    `on_phase` に今の段 (= `office` = pdf にしている / `render` = 頁の画像にしている) を知らせる。
    """
    kind = kind_of(source)
    if kind is None:
        raise ConversionError("unreadable")
    out_dir.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="cpc-pages-") as tmp:
        work = Path(tmp)
        if kind == "tiff":
            on_phase("office")
            _tiff_to_images(source, out_dir, work, on_phase)
        else:
            if kind == "office":
                on_phase("office")
                pdf = _office_to_pdf(source, work)
            else:
                pdf = source
            on_phase("render")
            _pdf_to_images(pdf, out_dir, work, ["-r", str(DPI)])
    pages = sorted(out_dir.glob("p-*.jpg"))
    if not pages:
        raise ConversionError("no_pages")
    return [jpeg_size(page) for page in pages]
