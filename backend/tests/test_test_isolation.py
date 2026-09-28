"""test が動いている backend の file を書かないことの確認。

test は backend.main を import するだけで log handler を付ける。 その先が repo の logs/ だと、
test がわざと起こす例外が本番の backend.error.log に混ざる (= conftest.py が CPC_LOGS_DIR を
使い捨ての folder に向けている)。
"""
import logging
import pathlib

from backend import paths

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent.parent


def test_logs_go_to_a_throwaway_folder_not_the_repository():
    assert paths.LOGS_DIR != REPO_ROOT / "logs"
    assert REPO_ROOT not in paths.LOGS_DIR.parents


def test_no_log_handler_writes_into_the_repository():
    import backend.main  # noqa: F401  (= handler を付けるのは import した時)
    files = [pathlib.Path(h.baseFilename) for lg in (logging.getLogger(), logging.getLogger("uvicorn.access"))
             for h in lg.handlers if isinstance(h, logging.FileHandler)]
    assert files, "backend.main attached no file handler"
    assert all(REPO_ROOT not in f.parents for f in files), files
