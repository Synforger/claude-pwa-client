"""test が動いている backend の file を書かないことと、 前の test の設定を引きずらないことの確認。

test は backend.main を import するだけで log handler を付ける。 その先が repo の logs/ だと、
test がわざと起こす例外が本番の backend.error.log に混ざる (= conftest.py が CPC_LOGS_DIR を
使い捨ての folder に向けている)。
"""
import logging
import pathlib

from backend._common import paths

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent.parent.parent


def test_logs_go_to_a_throwaway_folder_not_the_repository():
    assert paths.LOGS_DIR != REPO_ROOT / "logs"
    assert REPO_ROOT not in paths.LOGS_DIR.parents


def test_no_log_handler_writes_into_the_repository():
    import backend.main  # noqa: F401  (= handler を付けるのは import した時)
    files = [pathlib.Path(h.baseFilename) for lg in (logging.getLogger(), logging.getLogger("uvicorn.access"))
             for h in lg.handlers if isinstance(h, logging.FileHandler)]
    assert files, "backend.main attached no file handler"
    assert all(REPO_ROOT not in f.parents for f in files), files


def test_a_config_name_left_behind_as_a_real_attribute_is_dropped():
    """monkeypatch の後始末が残す形 (= 設定から配られる名前に、 実体の属性が被さる) を作って、 取り除かれるのを見る。"""
    import backend._common.config as config
    from backend.tests.conftest import drop_shadowed_config_names
    config.AGENTS = {"left_behind": {}}
    assert drop_shadowed_config_names() == ["AGENTS"]
    assert "left_behind" not in config.AGENTS
    assert drop_shadowed_config_names() == []


def test_a_patched_config_name_does_not_reach_the_next_test_1_of_2(monkeypatch):
    import backend._common.config as config
    monkeypatch.setattr(config, "AGENTS", {"patched": {}})
    assert "patched" in config.AGENTS


def test_a_patched_config_name_does_not_reach_the_next_test_2_of_2():
    import backend._common.config as config
    assert "patched" not in config.AGENTS
    assert "AGENTS" not in vars(config)
