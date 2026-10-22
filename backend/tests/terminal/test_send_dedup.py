"""backend/terminal/send_dedup.py の単体テスト。

責務 3 つを個別に確認:
    1. check_and_mark: 2 発目 (sid, send_id) を drop する
    2. bind_jsonl_uuid: 未 mapping 最古の send_id に uuid を焼く (時刻順先勝ち)
    3. send_id_for_uuid: 逆引きで送信元 send_id を返す
"""
from __future__ import annotations

import time

from backend.terminal.send_dedup import SendDedup


def test_check_and_mark_first_returns_false():
    d = SendDedup()
    assert d.check_and_mark("sid_a", "s1") is False


def test_check_and_mark_second_returns_true():
    d = SendDedup()
    d.check_and_mark("sid_a", "s1")
    assert d.check_and_mark("sid_a", "s1") is True


def test_check_and_mark_different_sid_are_independent():
    d = SendDedup()
    d.check_and_mark("sid_a", "s1")
    # 別 sid の同 send_id は別 key なので通す
    assert d.check_and_mark("sid_b", "s1") is False


def test_check_and_mark_different_send_id_are_independent():
    d = SendDedup()
    d.check_and_mark("sid_a", "s1")
    assert d.check_and_mark("sid_a", "s2") is False


def test_bind_jsonl_uuid_returns_oldest_unmapped_send_id():
    """未 mapping 最古 の send_id に jsonl_uuid を焼く。 text 一致は使わない。"""
    d = SendDedup()
    d.check_and_mark("sid_a", "s1")
    time.sleep(0.01)
    d.check_and_mark("sid_a", "s2")
    bound = d.bind_jsonl_uuid("sid_a", "u1")
    assert bound == "s1"  # 先に mark された s1 が先勝ち


def test_bind_jsonl_uuid_second_call_returns_next_oldest():
    """1 発目の bind が最古を消費した後、 2 発目は次の最古を掴む。"""
    d = SendDedup()
    d.check_and_mark("sid_a", "s1")
    time.sleep(0.01)
    d.check_and_mark("sid_a", "s2")
    d.bind_jsonl_uuid("sid_a", "u1")
    bound2 = d.bind_jsonl_uuid("sid_a", "u2")
    assert bound2 == "s2"


def test_bind_jsonl_uuid_returns_none_when_no_candidate():
    d = SendDedup()
    assert d.bind_jsonl_uuid("sid_a", "u1") is None


def test_bind_jsonl_uuid_ignores_other_sid():
    """他 sid の未 mapping は候補にしない (= sid 別空間)。"""
    d = SendDedup()
    d.check_and_mark("sid_a", "s1")
    assert d.bind_jsonl_uuid("sid_b", "u1") is None


def test_send_id_for_uuid_reverse_lookup():
    d = SendDedup()
    d.check_and_mark("sid_a", "s1")
    d.bind_jsonl_uuid("sid_a", "u1")
    assert d.send_id_for_uuid("sid_a", "u1") == "s1"


def test_send_id_for_uuid_returns_none_for_unknown_uuid():
    d = SendDedup()
    assert d.send_id_for_uuid("sid_a", "u-missing") is None


def test_ttl_expiry_purges_entries():
    """TTL 経過後の entry は check / bind で見えない。"""
    d = SendDedup(ttl_sec=0.05)
    d.check_and_mark("sid_a", "s1")
    time.sleep(0.1)
    # TTL 超えた entry は purge されるので 2 発目 s1 が「新規」 として通る
    assert d.check_and_mark("sid_a", "s1") is False


def test_max_entries_evicts_oldest():
    """entry 上限超過時、 最古から evict される (memory bounded)。"""
    d = SendDedup(max_entries=3)
    d.check_and_mark("sid_a", "s1")
    time.sleep(0.005)
    d.check_and_mark("sid_a", "s2")
    time.sleep(0.005)
    d.check_and_mark("sid_a", "s3")
    time.sleep(0.005)
    d.check_and_mark("sid_a", "s4")  # ← s1 が evict される想定
    # s1 は evict されたので dedup が抜ける (= 「新規」 として通る)
    assert d.check_and_mark("sid_a", "s1") is False
    # 直近 3 発の s2/s3/s4 は残っているので dedup 継続
    assert d.check_and_mark("sid_a", "s4") is True
