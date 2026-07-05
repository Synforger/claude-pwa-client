"""_confirm_after_send の救済 Enter 分岐を verify する (= 2026-07-05 picker 誤確定 fix)。

/model 等 picker を開く slash command は JSONL 確認が timeout する (= picker 表示中は
command 完了行が書かれない)。 その時に救済 Enter を打つと picker の現選択を勝手に
確定するので、 pane に対話 UI が見えていたら救済しない。
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
def rescue_env(monkeypatch, tmp_path):
    """JSONL 確認が常に timeout する環境 + 差し替え可能な pane state。"""
    jsonl = tmp_path / "session.jsonl"
    jsonl.write_text("")

    sent_keys: list[dict] = []
    pane = {"tail": "", "alternate": False, "cursor_y": 5}

    monkeypatch.setattr(confirm_mod, "get_pane_cursor_y", lambda sid: pane["cursor_y"])
    monkeypatch.setattr(confirm_mod, "capture_pane_plain_tail", lambda sid: pane["tail"])
    monkeypatch.setattr(confirm_mod, "get_pane_alternate_on", lambda sid: pane["alternate"])

    def _fake_send(sid, text=None, key=None, enter=False):
        sent_keys.append({"text": text, "key": key, "enter": enter})
        return True

    monkeypatch.setattr(confirm_mod, "tmux_send_keys", _fake_send)

    # wait を即 timeout させる (= 4s 待たない)
    async def _never_confirms(counter, path, initial_pos, timeout):
        return False

    monkeypatch.setattr(confirm_mod, "_wait_count_added", _never_confirms)
    return jsonl, pane, sent_keys


def test_rescue_enter_skipped_when_picker_open(rescue_env):
    """picker (= inline TUI) が pane に見えている間は救済 Enter を打たない。"""
    jsonl, pane, sent_keys = rescue_env
    pane["tail"] = (
        "  Select model\n"
        "    1. Default    Opus 4.8\n"
        "  ❯ 3. Fable ✔   Fable 5\n"
        "    5. Haiku      Haiku 4.5"
    )

    result = _run(confirm_mod._confirm_after_send("sid", "/model", jsonl, 0, True))
    assert result["confirmed"] is False
    assert result["reason"] == "interactive_ui_open"
    assert sent_keys == []  # 救済 Enter なし


def test_rescue_enter_skipped_when_alternate_screen(rescue_env):
    """full-screen TUI (= alternate buffer) 中も救済しない。"""
    jsonl, pane, sent_keys = rescue_env
    pane["tail"] = "some editor content"
    pane["alternate"] = True

    result = _run(confirm_mod._confirm_after_send("sid", "text", jsonl, 0, False))
    assert result["reason"] == "interactive_ui_open"
    assert sent_keys == []


def test_rescue_enter_fires_on_plain_stall(rescue_env):
    """対話 UI が無い普通の未達 (= text が入力欄に残ってるだけ) は従来通り救済する。"""
    jsonl, pane, sent_keys = rescue_env
    pane["tail"] = "❯ some half-typed message"

    result = _run(confirm_mod._confirm_after_send("sid", "hello", jsonl, 0, False))
    # 救済 Enter が 1 回打たれている
    assert any(k["enter"] for k in sent_keys)
    assert result["confirmed"] is False


def test_rescue_skipped_when_cursor_home(rescue_env):
    """cursor_y == 0 (= text が pane に渡ってない) は既存挙動どおり救済しない。"""
    jsonl, pane, sent_keys = rescue_env
    pane["cursor_y"] = 0

    result = _run(confirm_mod._confirm_after_send("sid", "hello", jsonl, 0, False))
    assert result["reason"] == "cursor_home"
    assert sent_keys == []
