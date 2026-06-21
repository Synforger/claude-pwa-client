"""JsonlEventBroadcaster の unit test (= F-02 / F-06)。

pub/sub の sid 別 + "all" 振分、 publish 後 Queue 受信、 unsubscribe で漏れない、
複数 subscriber に fan-out、 などの基本動作を担保する。

pytest-asyncio が無いので各 async ケースは loop を都度作って run する。 asyncio.run は
default loop を閉じて後続 test (= test_fork.py の `asyncio.get_event_loop()` 経路) を壊す
ので、 new_event_loop + set_event_loop で main thread に新 loop を張り直す helper を使う。
"""
import asyncio

from backend.state import (
    ALL_SUBSCRIBER_KEY,
    JsonlEventBroadcaster,
    jsonl_event_broadcaster,
)


def _run(coro):
    loop = asyncio.new_event_loop()
    try:
        asyncio.set_event_loop(loop)
        return loop.run_until_complete(coro)
    finally:
        loop.close()
        asyncio.set_event_loop(asyncio.new_event_loop())


def test_subscribe_returns_queue_and_counts():
    async def run():
        b = JsonlEventBroadcaster()
        assert b.subscriber_count("sid_a") == 0
        q = b.subscribe("sid_a")
        assert isinstance(q, asyncio.Queue)
        assert b.subscriber_count("sid_a") == 1
        b.unsubscribe("sid_a", q)
        assert b.subscriber_count("sid_a") == 0
    _run(run())


def test_publish_delivers_to_sid_subscriber():
    async def run():
        b = JsonlEventBroadcaster()
        q = b.subscribe("sid_a")
        b.publish("sid_a", {"type": "assistant", "text": "hi", "sid": "sid_a"})
        ev = await asyncio.wait_for(q.get(), timeout=0.1)
        assert ev["text"] == "hi"
        assert ev["sid"] == "sid_a"
    _run(run())


def test_publish_does_not_cross_sids():
    async def run():
        b = JsonlEventBroadcaster()
        qa = b.subscribe("sid_a")
        qb = b.subscribe("sid_b")
        b.publish("sid_a", {"type": "x", "sid": "sid_a"})
        ev = await asyncio.wait_for(qa.get(), timeout=0.1)
        assert ev["sid"] == "sid_a"
        try:
            await asyncio.wait_for(qb.get(), timeout=0.05)
        except asyncio.TimeoutError:
            return
        raise AssertionError("sid_b queue should not have received sid_a event")
    _run(run())


def test_publish_fans_out_to_all_subscriber():
    async def run():
        b = JsonlEventBroadcaster()
        qa = b.subscribe("sid_a")
        qall = b.subscribe(ALL_SUBSCRIBER_KEY)
        b.publish("sid_a", {"type": "assistant", "sid": "sid_a"})
        b.publish("sid_b", {"type": "assistant", "sid": "sid_b"})
        ev1 = await asyncio.wait_for(qa.get(), timeout=0.1)
        assert ev1["sid"] == "sid_a"
        assert qa.empty()
        seen = set()
        for _ in range(2):
            ev = await asyncio.wait_for(qall.get(), timeout=0.1)
            seen.add(ev["sid"])
        assert seen == {"sid_a", "sid_b"}
    _run(run())


def test_unsubscribe_stops_delivery():
    async def run():
        b = JsonlEventBroadcaster()
        q = b.subscribe("sid_a")
        b.unsubscribe("sid_a", q)
        b.publish("sid_a", {"type": "x", "sid": "sid_a"})
        try:
            await asyncio.wait_for(q.get(), timeout=0.05)
        except asyncio.TimeoutError:
            return
        raise AssertionError("queue should be empty after unsubscribe")
    _run(run())


def test_multiple_sid_subscribers_each_get_event():
    async def run():
        b = JsonlEventBroadcaster()
        q1 = b.subscribe("sid_a")
        q2 = b.subscribe("sid_a")
        b.publish("sid_a", {"type": "x", "sid": "sid_a"})
        ev1 = await asyncio.wait_for(q1.get(), timeout=0.1)
        ev2 = await asyncio.wait_for(q2.get(), timeout=0.1)
        assert ev1["sid"] == ev2["sid"] == "sid_a"
    _run(run())


def test_module_singleton_exists():
    """jsonl_event_broadcaster は state.py の module-level singleton として export 済。"""
    assert isinstance(jsonl_event_broadcaster, JsonlEventBroadcaster)
