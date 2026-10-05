"""同じ session への本文送信は 1 通ずつ通る (= `routes._send_body`)。

本文を打つ手順は「入力欄を消す → 貼る → 待つ → Enter」 で、 途中に待ちが在る。 並べずに通していた間は、
人の送信と、 同じ頃に届いた別のタブからの連絡が重なると、 後の 1 通の「入力欄を消す」 が先の 1 通の貼った
文を Enter の前に消し、 人の発話が届かなかった。 さらに、 届いたかの確かめは「発話の行が増えたか」 しか
見ないので、 消された側の送信が、 もう 1 通の行を自分の物と数えて「届いた」 と返した。

tmux と claude は立てない。 「端末へ打つ」 と「行が書かれるのを待つ」 を差し替えて、 打たれた順だけを見る。
"""
from __future__ import annotations

import asyncio
import json

import pytest

import backend.terminal.routes as routes
import backend.terminal.runner as runner

ENTER_DELAY = 0.05


@pytest.fixture
def pane(monkeypatch, tmp_path):
    """1 つの入力欄を持つ端末の身代わり: 消す / 貼る / Enter を、 打たれた順に記録する。 Enter で、 その時
    入力欄に在る文が 1 行の発話として会話の記録に書かれる (= 空の入力欄への Enter は何も書かない)。"""
    record = tmp_path / "conversation.jsonl"
    record.write_text("")
    state = {"keys": [], "box": {}, "delivered": []}

    def wipe(session_id):
        state["keys"].append((session_id, "wipe"))
        state["box"][session_id] = ""

    def send_keys(session_id, text=None, key=None, enter=False):
        if text:
            state["keys"].append((session_id, f"paste:{text}"))
            state["box"][session_id] = state["box"].get(session_id, "") + text
        if key:
            state["keys"].append((session_id, f"key:{key}"))
        if enter:
            state["keys"].append((session_id, "enter"))
            said, state["box"][session_id] = state["box"].get(session_id, ""), ""
            if said:
                state["delivered"].append((session_id, said))
                with record.open("a") as fh:
                    fh.write(json.dumps({"type": "user", "message": {"role": "user", "content": said}}) + "\n")
        return True

    async def never_launches(session_id, text):
        return None

    async def ready(session_id):
        return True

    monkeypatch.setattr(runner, "wipe_input_line", wipe)
    monkeypatch.setattr(runner, "tmux_send_keys", send_keys)
    monkeypatch.setattr(runner, "TWO_STAGE_ENTER_DELAY_SEC", ENTER_DELAY)
    monkeypatch.setattr(routes, "tmux_send_keys", send_keys)
    monkeypatch.setattr(routes, "_require_session", lambda _sid: None)
    monkeypatch.setattr(routes, "launch_with_first_message", never_launches)
    monkeypatch.setattr(routes, "wait_ready", ready)
    monkeypatch.setattr(routes, "jsonl_path_for_session", lambda _sid: record)
    monkeypatch.setattr(routes, "_send_locks", {})
    monkeypatch.setattr(routes, "stream_states", {})
    monkeypatch.delenv("CPC_E2E", raising=False)
    return state


def send(session_id: str, text: str):
    return routes.pty_send(session_id, {"text": text, "enter": True}, None)


def together(*sends):
    async def run():
        return await asyncio.gather(*sends)
    return asyncio.run(run())


def test_two_bodies_sent_together_both_arrive_whole(pane):
    """人の発話と、 同じ頃に届いた連絡: どちらも、 自分の文のまま届く。"""
    results = together(send("ses_a", "what the operator typed"), send("ses_a", "a message from another tab"))
    assert sorted(said for _sid, said in pane["delivered"]) == ["a message from another tab", "what the operator typed"]
    assert [r["ok"] for r in results] == [True, True]


def test_the_keys_of_one_body_are_not_cut_into_by_another(pane):
    together(send("ses_a", "first"), send("ses_a", "second"), send("ses_a", "third"))
    keys = [what for _sid, what in pane["keys"]]
    assert len(keys) == 9
    for start in (0, 3, 6):
        wipe, paste, enter = keys[start:start + 3]
        assert (wipe, enter) == ("wipe", "enter") and paste.startswith("paste:"), keys
    assert {keys[1], keys[4], keys[7]} == {"paste:first", "paste:second", "paste:third"}


def test_a_body_is_confirmed_by_its_own_line_not_by_the_one_before_it(pane, monkeypatch):
    """次の 1 通は、 前の 1 通の行が書かれるのを見届けてから打つ ― 数え始めの位置が、 前の 1 通の行より後ろ。"""
    seen: list[tuple[str, int, int]] = []

    async def confirm(session_id, text, jsonl_path, initial_pos, is_slash):
        seen.append((text, initial_pos, jsonl_path.stat().st_size))
        return {"ok": True, "confirmed": jsonl_path.stat().st_size > initial_pos}

    monkeypatch.setattr(routes, "_confirm_after_send", confirm)
    results = together(send("ses_a", "first"), send("ses_a", "second"))
    assert [r["confirmed"] for r in results] == [True, True]
    (_t1, start1, end1), (_t2, start2, _end2) = seen
    assert start1 == 0
    assert start2 == end1 > 0, "the second body starts counting after the first one's line"


def test_while_a_turn_runs_the_next_body_does_not_wait_for_the_line(pane, monkeypatch):
    """turn の実行中は、 送った発話は queue に積まれて行が書かれない。 確かめを持ったまま次を待たせない。"""
    order: list[str] = []
    typed = runner.send_text_two_stage

    async def typing(session_id, text, key=None):
        order.append(f"typed:{text}")
        return await typed(session_id, text, key=key)

    async def slow_confirm(session_id, text, jsonl_path, initial_pos, is_slash):
        await asyncio.sleep(ENTER_DELAY * 6)
        order.append(f"gave up:{text}")
        return {"ok": True, "confirmed": False}

    from backend.state import StreamState

    busy = StreamState()
    busy.busy = True
    monkeypatch.setattr(routes, "send_text_two_stage", typing)
    monkeypatch.setattr(routes, "_confirm_after_send", slow_confirm)
    monkeypatch.setattr(routes, "stream_states", {"ses_a": busy})
    together(send("ses_a", "first"), send("ses_a", "second"))
    assert order[:2] == ["typed:first", "typed:second"], order
    assert busy.queued_sends == 2


def test_a_turn_that_is_not_running_makes_the_next_body_wait_for_the_line(pane, monkeypatch):
    order: list[str] = []
    typed = runner.send_text_two_stage

    async def typing(session_id, text, key=None):
        order.append(f"typed:{text}")
        return await typed(session_id, text, key=key)

    async def confirm(session_id, text, jsonl_path, initial_pos, is_slash):
        await asyncio.sleep(ENTER_DELAY)
        order.append(f"confirmed:{text}")
        return {"ok": True, "confirmed": True}

    monkeypatch.setattr(routes, "send_text_two_stage", typing)
    monkeypatch.setattr(routes, "_confirm_after_send", confirm)
    together(send("ses_a", "first"), send("ses_a", "second"))
    assert order == ["typed:first", "confirmed:first", "typed:second", "confirmed:second"]


def test_a_key_to_stop_is_not_kept_waiting_behind_a_body(pane):
    """Escape (= 停止) は並ばない。 本文を打っている最中でも、 すぐ打たれる。"""
    async def run():
        body = asyncio.create_task(send("ses_a", "a long body"))
        await asyncio.sleep(ENTER_DELAY / 5)        # 本文が貼られて、 Enter を待っている間
        await routes.pty_send("ses_a", {"key": "Escape"}, None)
        stopped_at = len(pane["keys"])
        await body
        return stopped_at

    stopped_at = asyncio.run(run())
    keys = [what for _sid, what in pane["keys"]]
    assert keys.index("key:Escape") < keys.index("enter")
    assert stopped_at < len(keys)


def test_bodies_to_different_tabs_do_not_wait_for_each_other(pane):
    together(send("ses_a", "to a"), send("ses_b", "to b"))
    keys = pane["keys"]
    # 2 つのタブの「貼る」 が、 どちらの Enter よりも前に在る (= 互いを待っていない)
    first_enter = next(i for i, (_sid, what) in enumerate(keys) if what == "enter")
    assert {sid for sid, what in keys[:first_enter] if what.startswith("paste:")} == {"ses_a", "ses_b"}
    assert sorted(pane["delivered"]) == [("ses_a", "to a"), ("ses_b", "to b")]


def test_a_body_with_files_goes_through_the_same_door(pane, monkeypatch):
    """添付の付いた本文も、 素の本文と同じ所を 1 通ずつ通る。"""
    async def saved(files, session_id):
        return []

    monkeypatch.setattr(routes, "save_to_tmp", saved)
    results = together(send("ses_a", "plain"), routes.pty_send_with_files("ses_a", text="with a file", files=[], idempotency_key=None))
    assert sorted(said for _sid, said in pane["delivered"]) == ["plain", "with a file"]
    assert results[1]["saved_files"] == []
    keys = [what for _sid, what in pane["keys"]]
    assert [keys[i] for i in (0, 2, 3, 5)] == ["wipe", "enter", "wipe", "enter"]
