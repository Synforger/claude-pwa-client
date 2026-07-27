"""broadcast_push の実体テスト (= webpush 送信のみ差し替え、 本体は実走)。

従来は broadcast_push 自体を monkeypatch で丸ごと差し替えるテストしか無く、
viewed 抑止 / 未読カウンタ / dead subscription 除去の実装が壊れても全テストが
緑のままだった (= 2026-07-27 退役 audit の finding)。 本 file は実装そのものを
async で実行し、 外部送信 (pywebpush) だけを偽物にする。
"""
from __future__ import annotations

import asyncio

import backend.core.push as push_mod
import backend.state as state_mod


def _run(coro):
    loop = asyncio.new_event_loop()
    try:
        asyncio.set_event_loop(loop)
        return loop.run_until_complete(coro)
    finally:
        loop.close()
        asyncio.set_event_loop(asyncio.new_event_loop())


class _FakeResp:
    def __init__(self, status):
        self.status_code = status


def _setup(monkeypatch, subs, sent, dead_status=None):
    """push module を「送れる」 状態に整え、 webpush を記録 stub に差し替える。"""
    monkeypatch.setattr(push_mod, "_HAS_WEBPUSH", True)
    monkeypatch.setattr(push_mod, "vapid_config", {"private_b64": "test-key"})
    monkeypatch.setattr(push_mod, "subscriptions", subs)
    monkeypatch.setattr(push_mod, "unread_count", 0)
    removed = []
    monkeypatch.setattr(push_mod, "_atomic_remove_dead_subscriptions", removed.extend)

    def fake_webpush(subscription_info, **kwargs):
        sent.append(subscription_info)
        if dead_status is not None and subscription_info.get("dead"):
            raise push_mod.WebPushException("gone", response=_FakeResp(dead_status))

    monkeypatch.setattr(push_mod, "webpush", fake_webpush)
    return removed


def test_broadcast_sends_and_bumps_unread(monkeypatch):
    """基本経路: 全 subscription へ送信 + 未読カウンタ +1。"""
    sent: list = []
    _setup(monkeypatch, [{"endpoint": "a"}, {"endpoint": "b"}], sent)
    monkeypatch.setattr(state_mod, "views_by_conn", {})
    _run(push_mod.broadcast_push("hello", session_id="ses_x"))
    assert len(sent) == 2
    assert push_mod.unread_count == 1


def test_broadcast_skipped_when_session_viewed(monkeypatch):
    """該当 session を見ている接続があれば送信もカウンタも動かない。"""
    sent: list = []
    _setup(monkeypatch, [{"endpoint": "a"}], sent)
    monkeypatch.setattr(state_mod, "views_by_conn", {"conn1": "ses_x"})
    _run(push_mod.broadcast_push("hello", session_id="ses_x"))
    assert sent == []
    assert push_mod.unread_count == 0


def test_broadcast_collects_dead_subscriptions(monkeypatch):
    """410 Gone の subscription は dead 除去経路に載る。"""
    sent: list = []
    removed = _setup(
        monkeypatch,
        [{"endpoint": "ok"}, {"endpoint": "gone", "dead": True}],
        sent,
        dead_status=410,
    )
    monkeypatch.setattr(state_mod, "views_by_conn", {})
    _run(push_mod.broadcast_push("hello", session_id="ses_x"))
    assert len(sent) == 2
    assert [s["endpoint"] for s in removed] == ["gone"]
