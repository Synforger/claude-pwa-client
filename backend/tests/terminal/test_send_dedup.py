"""backend/terminal/send_dedup.py の単体テスト。

責務 3 つを個別に確認:
    1. check_and_mark: 2 発目 (sid, send_id) を drop する
    2. bind_jsonl_uuid: 未 mapping 最古の send_id に uuid を焼く (時刻順先勝ち)
    3. send_id_for_uuid: 逆引きで送信元 send_id を返す
"""
from __future__ import annotations

import time

from backend.terminal import sent_keys_store
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


def test_repeat_long_after_the_first_is_still_dropped():
    """A repeat that comes after the binding window (the app was behind with the answer cut off) is not typed again."""
    d = SendDedup(ttl_sec=0.05)
    d.check_and_mark("sid_a", "s1")
    time.sleep(0.1)
    assert d.check_and_mark("sid_a", "s1") is True


def test_binding_candidate_expires_after_ttl():
    """A send that never became a user row stops being a binding candidate once its window ends."""
    d = SendDedup(ttl_sec=0.05)
    d.check_and_mark("sid_a", "s1")
    time.sleep(0.1)
    assert d.bind_jsonl_uuid("sid_a", "u1") is None


def test_max_entries_bounds_binding_candidates_only():
    """Over the candidate limit the oldest candidate goes, but its key is still remembered for dedup."""
    d = SendDedup(max_entries=3)
    for send_id in ("s1", "s2", "s3", "s4"):
        d.check_and_mark("sid_a", send_id)
        time.sleep(0.005)
    assert d.bind_jsonl_uuid("sid_a", "u1") == "s2"
    assert d.check_and_mark("sid_a", "s1") is True


def test_max_seen_drops_the_oldest_key():
    """The dedup memory is bounded by count: past the limit the oldest key is forgotten."""
    d = SendDedup(max_seen=3)
    for send_id in ("s1", "s2", "s3", "s4"):
        d.check_and_mark("sid_a", send_id)
    assert d.check_and_mark("sid_a", "s1") is False
    assert d.check_and_mark("sid_a", "s4") is True


def test_reset_forgets_typed_keys():
    d = SendDedup()
    d.check_and_mark("sid_a", "s1")
    d.reset()
    assert d.check_and_mark("sid_a", "s1") is False


def test_stored_keys_survive_a_restart():
    """A send typed before the backend restarted is not typed again when the screen posts it after the restart."""
    SendDedup(is_stored=True).check_and_mark("sid_a", "s1")
    after_restart = SendDedup(is_stored=True)
    assert after_restart.check_and_mark("sid_a", "s1") is True
    assert after_restart.check_and_mark("sid_a", "s2") is False


def test_an_unstored_instance_writes_no_file():
    SendDedup().check_and_mark("sid_a", "s1")
    assert sent_keys_store.load() == []


def test_stored_file_is_written_again_with_the_remembered_keys_only():
    """The file grows to twice the remembered count, then keeps only what is remembered, newest kept."""
    d = SendDedup(is_stored=True, max_seen=2)
    for send_id in ("s1", "s2", "s3", "s4", "s5"):
        d.check_and_mark("sid_a", send_id)
    assert len(sent_keys_store.SENT_KEYS_PATH.read_text(encoding="utf-8").splitlines()) <= 4
    after_restart = SendDedup(is_stored=True, max_seen=2)
    assert after_restart.check_and_mark("sid_a", "s5") is True
    assert after_restart.check_and_mark("sid_a", "s1") is False


def test_unreadable_stored_file_starts_empty():
    sent_keys_store.SENT_KEYS_PATH.write_bytes(b"\xff\xfe broken")
    assert SendDedup(is_stored=True).check_and_mark("sid_a", "s1") is False


def test_key_that_does_not_fit_a_line_is_remembered_in_memory_only():
    d = SendDedup(is_stored=True)
    d.check_and_mark("sid_a", "bad\tkey")
    assert d.check_and_mark("sid_a", "bad\tkey") is True
    assert "bad" not in sent_keys_store.SENT_KEYS_PATH.read_text(encoding="utf-8")
