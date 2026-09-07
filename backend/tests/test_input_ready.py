"""claude が打鍵を受け取れるまで本文送信を待たせる旗の test。

セッション終了 (= restart) 直後は「tmux は在るが claude はまだ起動していない」 窓が
数秒ある。 そこへ本文 + Enter を打つと、 claude はまだ端末を読んでいないので入力が
端末の待ち行列に溜まり、 TUI が立ち上がった瞬間に 1 度に読まれる。 本文と Enter の
0.3s の間隔は読み手が読んでいなければ消えるので、 Enter が確定でなく本文の改行として
入り、 本文だけが入力欄に残る (= 2026-09-08 実測: SessionStart hook より前の送信は
14 件とも未達、 後なら 30 件中 25 件が 0.1s 以内)。
"""
import asyncio

import pytest

from backend.terminal import input_ready


@pytest.fixture(autouse=True)
def _clean_slots():
    input_ready._events.clear()
    yield
    input_ready._events.clear()


def test_unknown_session_is_not_held():
    """一度も spawn を見ていない sid は判定材料が無いので素通し (= 従来挙動を壊さない)。"""
    assert input_ready.is_ready("ses_never_seen") is True
    assert asyncio.run(input_ready.wait_ready("ses_never_seen")) is True


def test_starting_blocks_until_claude_reports_startup():
    """起動中は待ち、 SessionStart hook (= mark_ready) が来た瞬間に解ける。"""
    async def scenario():
        input_ready.mark_starting("ses_x")
        assert input_ready.is_ready("ses_x") is False
        waiter = asyncio.create_task(input_ready.wait_ready("ses_x", timeout=5))
        await asyncio.sleep(0)
        assert not waiter.done(), "起動中なのに待たずに通した"
        input_ready.mark_ready("ses_x")
        assert await waiter is True
    asyncio.run(scenario())


def test_timeout_gives_up_and_stops_holding_later_sends():
    """上限を超えたら False を返し、 以降の送信は待たせない (= 検出が効いていない環境で
    毎回 20 秒待たせない)。"""
    async def scenario():
        input_ready.mark_starting("ses_x")
        assert await input_ready.wait_ready("ses_x", timeout=0.01) is False
        # 2 発目は素通し
        assert await input_ready.wait_ready("ses_x", timeout=0.01) is True
    asyncio.run(scenario())


def test_restart_puts_the_flag_back_down():
    """ready の後にもう一度 restart したら再び待たせる。"""
    input_ready.mark_ready("ses_x")
    assert input_ready.is_ready("ses_x") is True
    input_ready.mark_starting("ses_x")
    assert input_ready.is_ready("ses_x") is False


def test_forget_drops_the_slot():
    input_ready.mark_starting("ses_x")
    input_ready.forget("ses_x")
    assert input_ready.is_ready("ses_x") is True


# --- endpoint の結線 ---

def _fake_tmux(monkeypatch, calls):
    import backend.terminal.routes as routes
    import backend.terminal.runner as runner

    def fake_send_keys(session_id, text=None, key=None, enter=False):
        calls.append({"text": text, "key": key, "enter": enter})
        return True

    monkeypatch.setattr(runner, "tmux_send_keys", fake_send_keys)
    monkeypatch.setattr(runner, "TWO_STAGE_ENTER_DELAY_SEC", 0)
    monkeypatch.setattr(runner, "USE_TMUX_WRAP", True)
    monkeypatch.setattr(runner, "has_tmux_session", lambda _sid: True)
    monkeypatch.setattr(runner, "_tmux_session_name", lambda _sid: "pwa-x")
    monkeypatch.setattr(runner, "_run_tmux", lambda *a, **k: None)
    monkeypatch.setattr(routes, "tmux_send_keys", fake_send_keys)
    monkeypatch.setattr(routes, "_require_session", lambda _sid: None)
    monkeypatch.setattr(routes, "jsonl_path_for_session", lambda _sid: None)
    return routes


def test_send_does_not_type_until_claude_is_up(monkeypatch):
    """起動中の pane には 1 打鍵も入れない。 ready になってから本文と Enter が出る。

    endpoint を直呼びする test は sid を共有しない: `Idempotency-Key` の既定値が
    FastAPI の Header object のまま渡るので、 同じ sid で 2 度呼ぶと send_dedup が
    2 発目を「連打」 と見て落とす (= 実運用では header の実値 or None が入る)。
    """
    calls: list[dict] = []
    routes = _fake_tmux(monkeypatch, calls)

    async def scenario():
        input_ready.mark_starting("ses_wait")
        send = asyncio.create_task(
            routes.pty_send("ses_wait", {"text": "hello", "enter": True})
        )
        for _ in range(20):
            await asyncio.sleep(0)
        assert calls == [], f"claude 起動前に打鍵している: {calls}"
        input_ready.mark_ready("ses_wait")
        out = await send
        assert out["ok"] is True
        assert calls == [
            {"text": "hello", "key": None, "enter": False},
            {"text": None, "key": None, "enter": True},
        ]
    asyncio.run(scenario())


def test_send_refuses_instead_of_typing_blind_after_the_timeout(monkeypatch):
    """待ち切れなかったら打鍵せず失敗を返す (= 本文は client 側の入力欄へ戻る)。"""
    calls: list[dict] = []
    routes = _fake_tmux(monkeypatch, calls)
    monkeypatch.setattr(input_ready, "INPUT_READY_TIMEOUT_SEC", 0.01)

    async def scenario():
        input_ready.mark_starting("ses_timeout")
        out = await routes.pty_send("ses_timeout", {"text": "hello", "enter": True})
        assert out == {"ok": False, "reason": "not_ready"}
        assert calls == [], f"待ち切れなかったのに打鍵している: {calls}"
    asyncio.run(scenario())


def test_single_keys_are_never_held(monkeypatch):
    """単発 key (= Escape で停止 / quick-reply) は待たせない (= 停止が遅れると害の方が大きい)。"""
    calls: list[dict] = []
    routes = _fake_tmux(monkeypatch, calls)

    async def scenario():
        input_ready.mark_starting("ses_key")
        out = await routes.pty_send("ses_key", {"key": "Escape"})
        assert out["ok"] is True
        assert calls == [{"text": None, "key": "Escape", "enter": False}]
    asyncio.run(scenario())
