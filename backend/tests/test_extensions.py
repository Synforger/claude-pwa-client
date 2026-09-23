"""config.json の `extensions` の読み取りと GET /extensions の shape。

拡張の置き場は `/ext/<id>/` に固定で、 config は id / title / icon だけを持つ。 不正な 1 件は
その 1 件だけ捨て、 理由は起動時の warn に出る。
"""
from __future__ import annotations

import json
import logging

import backend.config as config_mod
from backend._generated import http_endpoints as http
from backend.routes.extensions import list_extensions


def _write_config(tmp_path, monkeypatch, cfg):
    """conftest の autouse fixture と同じ作法で config を差し替える (= CONFIG_PATH + cache_clear)。"""
    path = tmp_path / "extensions-config.json"
    path.write_text(json.dumps(cfg), encoding="utf-8")
    monkeypatch.setattr(config_mod, "CONFIG_PATH", path)
    config_mod.get_config.cache_clear()


def test_no_extensions_key_means_empty(tmp_path, monkeypatch):
    _write_config(tmp_path, monkeypatch, {"agents": {}})
    assert list_extensions() == []


def test_empty_list_means_empty(tmp_path, monkeypatch):
    _write_config(tmp_path, monkeypatch, {"extensions": []})
    assert list_extensions() == []


def test_valid_entries_keep_config_order_and_derive_path(tmp_path, monkeypatch):
    _write_config(tmp_path, monkeypatch, {"extensions": [
        {"id": "reaper", "title": "REAPER", "icon": "🎚"},
        {"id": "budget-2"},
    ]})
    assert list_extensions() == [
        {"id": "reaper", "title": "REAPER", "icon": "🎚", "path": "/ext/reaper/"},
        {"id": "budget-2", "title": "budget-2", "icon": "🧩", "path": "/ext/budget-2/"},
    ]


def test_invalid_entries_are_dropped_one_by_one(tmp_path, monkeypatch):
    """1 件の書き損じで他の拡張が消えない。 path を config に書いても無視される。"""
    _write_config(tmp_path, monkeypatch, {"extensions": [
        {"id": "Reaper"},              # 大文字
        {"id": "../escape"},           # path を抜ける
        {"id": "-leading"},            # 先頭ハイフン
        {"id": "a" * 33},              # 33 文字
        {"title": "no id"},            # id 無し
        "reaper",                      # dict でない
        {"id": "ok", "path": "/elsewhere/"},
        {"id": "ok", "title": "dup"},  # 重複
    ]})
    assert list_extensions() == [
        {"id": "ok", "title": "ok", "icon": "🧩", "path": "/ext/ok/"},
    ]


def test_non_list_value_is_ignored(tmp_path, monkeypatch):
    _write_config(tmp_path, monkeypatch, {"extensions": {"id": "reaper"}})
    assert list_extensions() == []


def test_runtime_check_warns_each_dropped_entry(tmp_path, monkeypatch, caplog):
    _write_config(tmp_path, monkeypatch, {
        "agents": {"a": {}},
        "extensions": [{"id": "Bad"}, {"id": "good"}, {"id": "good"}],
    })
    with caplog.at_level(logging.WARNING, logger="backend.config"):
        config_mod.validate_runtime_paths()
    messages = [r.getMessage() for r in caplog.records]
    assert any("config.extensions[0] dropped: id must match" in m for m in messages)
    assert any("config.extensions[2] dropped: duplicate id 'good'" in m for m in messages)
    assert not any("extensions[1]" in m for m in messages)


def test_response_matches_the_contract(tmp_path, monkeypatch):
    _write_config(tmp_path, monkeypatch, {"extensions": [{"id": "reaper", "title": "REAPER", "icon": "🎚"}]})
    for item in list_extensions():
        http.GetExtensionsResponseItem.model_validate(item)


def test_route_is_served_by_the_app(tmp_path, monkeypatch):
    """app に router が載っていて、 SPA の静的配信より先に当たる (= "/" mount に食われない)。"""
    from fastapi.testclient import TestClient  # noqa: PLC0415
    from backend.main import app  # noqa: PLC0415
    _write_config(tmp_path, monkeypatch, {"extensions": [{"id": "reaper"}]})
    res = TestClient(app).get("/extensions")
    assert res.status_code == 200
    assert res.json() == [{"id": "reaper", "title": "reaper", "icon": "🧩", "path": "/ext/reaper/"}]
