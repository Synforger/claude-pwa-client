"""_confirm_after_send が観測専用 (= 介入しない) であることを verify する。

救済 Enter は 2026-07-05 に退役した (= confirm.py header 参照)。 このテストは
「confirm がどんな結果でも tmux にキーを送らない」 という退役後の契約を守る。
"""
from __future__ import annotations

import asyncio

import pytest

from backend.terminal import confirm as confirm_mod


def _run(coro):
    loop = asyncio.new_event_loop()
    try:
        asyncio.set_event_loop(loop)
        return loop.run_until_complete(coro)
    finally:
        loop.close()
        asyncio.set_event_loop(asyncio.new_event_loop())


@pytest.fixture
def confirm_env(monkeypatch, tmp_path):
    jsonl = tmp_path / "session.jsonl"
    jsonl.write_text("")
    return jsonl


def test_confirmed_true_when_prompt_appears(monkeypatch, confirm_env):
    async def _confirms(counter, path, initial_pos, timeout):
        return True

    monkeypatch.setattr(confirm_mod, "_wait_count_added", _confirms)
    result = _run(confirm_mod._confirm_after_send("sid", "hello", confirm_env, 0, False))
    assert result == {"ok": True, "confirmed": True}


def test_no_intervention_on_timeout(monkeypatch, confirm_env):
    """timeout しても confirmed=False を返すだけ (= 救済キー送信なし)。

    confirm module は tmux 送信系を import していないこと自体も契約
    (= 誤って復活させたら import が生えて目に見える)。"""
    async def _never(counter, path, initial_pos, timeout):
        return False

    monkeypatch.setattr(confirm_mod, "_wait_count_added", _never)
    result = _run(confirm_mod._confirm_after_send("sid", "/model", confirm_env, 0, True))
    assert result == {"ok": True, "confirmed": False}
    # 送信系 helper が module 名前空間に存在しない (= 退役の構造的確認)
    assert not hasattr(confirm_mod, "tmux_send_keys")
    assert not hasattr(confirm_mod, "get_pane_cursor_y")
