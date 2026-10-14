"""声の発話は、 turn の実行中なら先に止めてから届ける (= `routes._interrupt_for_voice`)。

声で長く話している間に agent が先へ進み続けないように、 頭に `[voice]` の印が付いた発話は、 turn の実行中なら
Escape で止め、 claude が中断の行を書くのを見届けてから打つ。 停止ボタン (= 止めて、 待っている入力も捨てる)
とは別の動きで、 発話は必ず届く。

tmux と claude は立てない。 端末の身代わり (= test_send_one_at_a_time の pane) に、 Escape で中断の行を書く
claude の振る舞いを足して、 打たれた順を見る。
"""
from __future__ import annotations

import json
import threading

import pytest

import backend.terminal.routes as routes
import backend.terminal.runner as runner
from backend.state import StreamState
from backend.tests.test_send_one_at_a_time import pane, send, together  # noqa: F401  (pane は fixture)

INTERRUPT = "[Request interrupted by user for tool use]"


@pytest.fixture
def claude(pane, monkeypatch, tmp_path):  # noqa: F811
    """turn を実行中の claude: Escape を受けると、 少し後に中断の行を書く (= 実測 0.2 秒台)。"""
    record = routes.jsonl_path_for_session("ses_a")
    state = {"busy": StreamState(busy=True), "writes_marker": True, "delay": 0.05}
    monkeypatch.setattr(routes, "stream_states", {"ses_a": state["busy"]})
    plain = runner.tmux_send_keys

    def send_keys(session_id, text=None, key=None, enter=False):
        ok = plain(session_id, text=text, key=key, enter=enter)
        if key == "Escape" and state["writes_marker"]:
            def write():
                pane["keys"].append((session_id, "marker"))
                with record.open("a") as fh:
                    fh.write(json.dumps({"type": "user", "message": {"role": "user", "content": [
                        {"type": "text", "text": INTERRUPT}]}}) + "\n")
            threading.Timer(state["delay"], write).start()
        return ok

    monkeypatch.setattr(runner, "tmux_send_keys", send_keys)
    monkeypatch.setattr(routes, "tmux_send_keys", send_keys)
    return state


def keys(pane):  # noqa: F811
    return [k for _, k in pane["keys"]]


def test_a_voice_turn_stops_the_running_turn_before_it_is_typed(pane, claude):  # noqa: F811
    result = together(send("ses_a", "[voice] やっぱりやめよう"))[0]
    assert result["ok"] is True
    assert keys(pane) == ["key:Escape", "marker", "wipe", "paste:[voice] やっぱりやめよう", "enter"]
    assert pane["delivered"] == [("ses_a", "[voice] やっぱりやめよう")]
    # 停止ボタンの印は付けない (= 次の turn の busy を押さえ込まない)
    assert claude["busy"].user_stopped is False


def test_a_typed_turn_does_not_stop_the_running_turn(pane, claude):  # noqa: F811
    together(send("ses_a", "続けて"))
    assert "key:Escape" not in keys(pane)
    assert pane["delivered"] == [("ses_a", "続けて")]


def test_a_voice_turn_to_an_idle_agent_is_only_typed(pane, claude):  # noqa: F811
    claude["busy"].busy = False
    together(send("ses_a", "[voice] こんにちは"))
    assert keys(pane) == ["wipe", "paste:[voice] こんにちは", "enter"]


def test_a_voice_turn_after_the_stop_button_is_only_typed(pane, claude):  # noqa: F811
    claude["busy"].user_stopped = True
    together(send("ses_a", "[voice] こんにちは"))
    assert "key:Escape" not in keys(pane)


def test_a_voice_turn_is_typed_even_when_no_stop_is_seen(pane, claude, monkeypatch):  # noqa: F811
    claude["writes_marker"] = False
    monkeypatch.setattr(routes, "VOICE_INTERRUPT_WAIT_SEC", 0.2)
    together(send("ses_a", "[voice] 聞こえる？"))
    assert keys(pane) == ["key:Escape", "wipe", "paste:[voice] 聞こえる？", "enter"]
    assert pane["delivered"] == [("ses_a", "[voice] 聞こえる？")]
