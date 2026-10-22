"""next_interval pure helper の unit test (= backend-F-42)。

SSE 配信 / push 監視で別々に書かれていた back-off ロジックを集約した helper。
- made_progress=True → base 間隔へ戻す
- made_progress=False → current * 1.5 (上限 _IDLE_MAX_INTERVAL=2.0)
"""
from backend.jsonl import routes as jr


def test_next_interval_progress_resets_to_base():
    """変化あり (= 行追加 / busy 維持) は次 tick も base 間隔。"""
    assert jr.next_interval(2.0, True) == jr.POLL_INTERVAL
    assert jr.next_interval(0.5, True) == jr.POLL_INTERVAL


def test_next_interval_idle_grows_by_factor():
    """変化なしは 1.5x ずつ伸ばす。"""
    assert jr.next_interval(0.5, False) == 0.75
    assert jr.next_interval(1.0, False) == 1.5


def test_next_interval_idle_caps_at_max():
    """上限 _IDLE_MAX_INTERVAL=2.0 を超えない。"""
    assert jr.next_interval(2.0, False) == jr._IDLE_MAX_INTERVAL
    assert jr.next_interval(5.0, False) == jr._IDLE_MAX_INTERVAL


def test_next_interval_monotone_growth_converges():
    """初期 POLL_INTERVAL から idle が続くと数 tick で上限へ収束する。"""
    cur = jr.POLL_INTERVAL
    for _ in range(20):
        cur = jr.next_interval(cur, False)
    assert cur == jr._IDLE_MAX_INTERVAL
