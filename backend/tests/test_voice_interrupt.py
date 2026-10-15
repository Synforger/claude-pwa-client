"""声の発話は、 turn の実行中なら先に止めてから届ける (= `routes._escape_for_voice`)。 停止ボタンは止めて消す。

声で長く話している間に agent が先へ進み続けないように、 頭に `[voice]` の印が付いた発話は、 turn の実行中なら
Escape で止め、 claude がそれを受け終えるのを見届けてから、 入力欄を消さずに後ろへ打つ。 claude は、 何も書き出す
前の turn を Escape で取り消すと、 送った文を入力欄へ戻す: 消さずに打てば、 前の発話と 1 つになって届く。
停止ボタン (= 止めて、 待っている入力も捨てる) は、 戻された文を消す。

tmux と claude は立てない。 端末の身代わり (= test_send_one_at_a_time の pane) に、 Escape で中断の行を書く /
送った文を入力欄へ戻す claude の振る舞いを足して、 打たれた順と届いた文を見る。
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
    """turn を実行中の claude: Escape を受けると、 少し後に (= 実測 0.2 秒前後)、 書き出した後なら中断の行を書き
    (= on_escape="marker")、 何も書き出す前なら最後に届いた発話を入力欄へ戻す (= "restore")。 "nothing" は何もしない。"""
    record = routes.jsonl_path_for_session("ses_a")
    state = {"busy": StreamState(busy=True), "on_escape": "marker", "delay": 0.05}
    monkeypatch.setattr(routes, "stream_states", {"ses_a": state["busy"]})
    monkeypatch.setattr(routes, "read_input_box", lambda session_id: pane["box"].get(session_id, ""))
    plain = runner.tmux_send_keys

    def send_keys(session_id, text=None, key=None, enter=False):
        ok = plain(session_id, text=text, key=key, enter=enter)
        if key == "Escape" and state["on_escape"] == "marker":
            def write():
                pane["keys"].append((session_id, "marker"))
                with record.open("a") as fh:
                    fh.write(json.dumps({"type": "user", "message": {"role": "user", "content": [
                        {"type": "text", "text": INTERRUPT}]}}) + "\n")
            threading.Timer(state["delay"], write).start()
        if key == "Escape" and state["on_escape"] == "restore":
            def restore():
                pane["keys"].append((session_id, "restore"))
                pane["box"][session_id] = pane["delivered"][-1][1]
            threading.Timer(state["delay"], restore).start()
        return ok

    monkeypatch.setattr(runner, "tmux_send_keys", send_keys)
    monkeypatch.setattr(routes, "tmux_send_keys", send_keys)
    return state


async def stop(session_id: str) -> dict:
    """停止ボタンを押して、 入力欄を消し終えるまで待つ。"""
    result = await routes.pty_send(session_id, {"key": "Escape"}, None)
    await routes._stop_clears.pop(session_id)
    return result


def keys(pane):  # noqa: F811
    return [k for _, k in pane["keys"]]


def test_a_voice_turn_stops_the_running_turn_before_it_is_typed(pane, claude):  # noqa: F811
    result = together(send("ses_a", "[voice] やっぱりやめよう"))[0]
    assert result["ok"] is True
    assert keys(pane) == ["key:Escape", "marker", "paste:[voice] やっぱりやめよう", "enter"]
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
    claude["on_escape"] = "nothing"
    monkeypatch.setattr(routes, "VOICE_INTERRUPT_WAIT_SEC", 0.2)
    together(send("ses_a", "[voice] 聞こえる？"))
    assert keys(pane) == ["key:Escape", "paste:[voice] 聞こえる？", "enter"]
    assert pane["delivered"] == [("ses_a", "[voice] 聞こえる？")]


def test_a_voice_turn_joins_the_turn_it_cancelled(pane, claude):  # noqa: F811
    # 途中の間で「言い終えた」 と判定された前半が先に送られ、 agent が何も書き出す前に後半が届いた。 Escape で
    # 取り消された前半は入力欄へ戻る。 入力欄を消していた間は、 前半がそこで消え、 agent は後半しか読まなかった
    # (= 2026-10-15、 一晩に 9 回)
    claude["busy"].busy = False
    together(send("ses_a", "[voice] うーん、モデル自体は小さい"))
    claude["busy"].busy = True
    claude["on_escape"] = "restore"
    together(send("ses_a", "[voice] まあでもそりゃそうか"))
    assert keys(pane)[3:] == ["key:Escape", "restore", "paste: まあでもそりゃそうか", "enter"]
    assert pane["delivered"][-1] == ("ses_a", "[voice] うーん、モデル自体は小さい まあでもそりゃそうか")


def test_the_stop_button_clears_what_the_stop_put_back(pane, claude):  # noqa: F811
    # 停止で入力欄へ戻った文 (= 取り消した発話と、 待っていた発話) は、 停止ボタンが消す
    claude["busy"].busy = False
    together(send("ses_a", "これをやって"))
    claude["busy"].busy = True
    claude["on_escape"] = "restore"
    result = together(stop("ses_a"))[0]
    assert result == {"ok": True}
    assert keys(pane)[3:] == ["key:Escape", "restore", "wipe"]
    assert pane["box"]["ses_a"] == ""


def test_the_stop_button_waits_for_the_escape_even_before_the_turn_shows_busy(pane, claude):  # noqa: F811
    # 送った直後は作業中の印がまだ立たない。 印を見て待たずに消していた間は、 Escape のすぐ後に消すキーが届き、
    # 端末が 2 つを Alt + キーと読んで停止が効かなかった。 印に関わらず、 受け終えるのを見届けてから消す
    claude["busy"].busy = False
    together(send("ses_a", "これをやって"))
    claude["on_escape"] = "restore"
    together(stop("ses_a"))
    assert keys(pane)[3:] == ["key:Escape", "restore", "wipe"]
    assert pane["box"]["ses_a"] == ""


def test_the_stop_button_on_an_idle_agent_still_clears(pane, claude, monkeypatch):  # noqa: F811
    claude["busy"].busy = False
    claude["on_escape"] = "nothing"
    monkeypatch.setattr(routes, "VOICE_INTERRUPT_WAIT_SEC", 0.2)
    together(stop("ses_a"))
    assert keys(pane) == ["key:Escape", "wipe"]


def test_the_input_box_is_read_between_the_last_two_rules():
    # claude 2.1.299 の画面 (= 色を外した物)。 履歴にも ❯ の行が在るので、 最後の 2 本の横線の間だけを読む
    rule = "─" * 40
    screen = "\n".join([
        "❯ [voice] 前に送った文",
        "⏺ 返事",
        rule,
        "❯ [voice] 戻された文",
        rule,
        "  [Opus 5.5] ctx:░░░░░░░░4%",
    ])
    assert runner.input_box_text(screen) == "[voice] 戻された文"
    assert runner.input_box_text("\n".join([rule, "❯ ", rule])) == ""
    assert runner.input_box_text("全画面の選択肢") is None


# --- 話している途中に言葉が取れた時 (= `routes.interrupt_for_voice`) ---------------------------------------------

def test_words_heard_while_speaking_stop_the_running_turn_and_the_turn_is_typed_after(pane, claude):  # noqa: F811
    assert together(routes.interrupt_for_voice("ses_a"))[0] is True
    together(send("ses_a", "[voice] やっぱりやめよう"))
    # Escape は話している途中の 1 回だけ (= 送る時に打ち直さない)
    assert keys(pane) == ["key:Escape", "marker", "paste:[voice] やっぱりやめよう", "enter"]
    assert pane["delivered"] == [("ses_a", "[voice] やっぱりやめよう")]
    assert claude["busy"].user_stopped is False


def test_words_heard_while_speaking_join_the_turn_the_stop_put_back(pane, claude):  # noqa: F811
    # 前の発話に agent が何も書き出す前に話し始めた: claude は前の発話を入力欄へ戻す。 送る時に Escape を打ち直すと、
    # 戻された文の上で打つことになり、 その文が消える
    claude["busy"].busy = False
    together(send("ses_a", "[voice] うーん、モデル自体は小さい"))
    claude["busy"].busy = True
    claude["on_escape"] = "restore"
    assert together(routes.interrupt_for_voice("ses_a"))[0] is True
    together(send("ses_a", "[voice] まあでもそりゃそうか"))
    assert keys(pane)[3:] == ["key:Escape", "restore", "paste: まあでもそりゃそうか", "enter"]
    assert pane["delivered"][-1] == ("ses_a", "[voice] うーん、モデル自体は小さい まあでもそりゃそうか")


def test_words_heard_while_the_agent_is_idle_or_stopped_do_nothing(pane, claude):  # noqa: F811
    claude["busy"].busy = False
    assert together(routes.interrupt_for_voice("ses_a"))[0] is False
    claude["busy"].busy = True
    claude["busy"].user_stopped = True
    assert together(routes.interrupt_for_voice("ses_a"))[0] is False
    assert keys(pane) == []
    assert routes._voice_escapes == {}


def test_a_typed_turn_after_an_early_stop_is_typed_as_usual_and_drops_the_stop(pane, claude):  # noqa: F811
    together(routes.interrupt_for_voice("ses_a"))
    together(send("ses_a", "続けて"))
    assert keys(pane) == ["key:Escape", "marker", "wipe", "paste:続けて", "enter"]
    assert routes._voice_escapes == {}
