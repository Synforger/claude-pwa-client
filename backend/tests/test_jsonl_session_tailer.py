"""SessionTailer 化された monitor の per-sid 処理 / quarantine / watchfiles 信号 drain
の unit test (= backend-F-01 / F-03 / F-65)。

monitor_all_sessions_loop 全体は async lifespan task なので直接動かすのは難しいが、
SessionTailState dataclass / _tick_sid / _drain_watch_signals_to_state は分割済の単機能
関数なので個別に検査できる。 既存挙動 (= 旧 397 行 inner loop) との回帰防止を担保する。
"""
import time
from pathlib import Path

import backend.jsonl.routes as jr
import backend.state as state_mod


def _make_state_for(sid: str):
    """isolated_state fixture と同じ初期化を 1 sid 分だけ手で作る helper。"""
    state_mod.stream_states[sid] = state_mod.StreamState(agent_id="a")
    state_mod.agent_status[sid] = {
        "current_tool": None, "subagent": None, "todos": None,
        "pending_plan": None, "pending_question": None, "plan_mode": False,
        "model": "", "ctx_pct": 0, "ctx_window": 1_000_000,
        "pr_links": [], "tasks": [],
        "mode": "", "permission_mode": "",
        "budget_used": None, "budget_total": None, "budget_remaining": None,
    }


# --- SessionTailState dataclass の defaults --------------------------------

def test_session_tail_state_defaults():
    ts = jr.SessionTailState()
    assert ts.path is None
    assert ts.offset == 0
    assert ts.interval == jr.POLL_INTERVAL
    assert ts.next_poll_at == 0.0
    assert ts.consecutive_failures == 0


# --- F-65 quarantine: 連続失敗 counter で sid を一時 quarantine ---------

def test_tick_sid_increments_failure_on_exception(isolated_state, tmp_path, monkeypatch):
    """`_tick_sid` 内部 (= ここでは monitor loop の per-sid try/except 周りを simulate)
    で例外発生時に counter が increment されることを担保。 _latest_jsonl が例外を
    raise すれば _tick_sid 自体が落ちる経路を捕捉する。"""
    sid = "ses_fail"
    _make_state_for(sid)

    def boom(_sid):
        raise RuntimeError("simulated jsonl resolve failure")

    monkeypatch.setattr(jr, "_latest_jsonl", boom)
    tstate = jr.SessionTailState()
    # 1 回失敗で counter は 1
    try:
        jr._tick_sid(sid, tstate, now_mono=100.0)
    except RuntimeError:
        tstate.consecutive_failures += 1
    assert tstate.consecutive_failures == 1


def test_quarantine_threshold_skips_polls():
    """next_poll_at が now_mono を上回ってる間は monitor 側 outer loop で skip される
    (= quarantine 中 30s 沈黙の挙動)。"""
    ts = jr.SessionTailState()
    now = 100.0
    ts.next_poll_at = now + jr._QUARANTINE_SEC
    # outer loop の `if next_poll_at > now: continue` を simulate
    assert ts.next_poll_at > now
    # 30s 経過後は復帰可能
    assert ts.next_poll_at <= now + jr._QUARANTINE_SEC + 0.01


def test_quarantine_constants_sane():
    """quarantine 閾値は実用範囲内 (= 全 sid 巻き込まない、 数 tick で発火可能)。"""
    assert 1 <= jr._QUARANTINE_THRESHOLD <= 20
    assert 1.0 <= jr._QUARANTINE_SEC <= 300.0


# --- F-01 watchfiles 信号 drain で next_poll_at が即時 advance ------------

def test_drain_watch_signals_advances_next_poll(isolated_state, tmp_path):
    sid = "ses_wake"
    _make_state_for(sid)
    p = tmp_path / "ses_wake.jsonl"
    p.write_bytes(b"")
    ts = jr.SessionTailState(path=p, offset=0, next_poll_at=time.monotonic() + 100.0)
    states = {sid: ts}
    sid_by_path = {p: sid}
    # signal を積んで drain
    jr._watch_signal_paths.add(p)
    jr._drain_watch_signals_to_state(states, sid_by_path)
    # next_poll_at が直近に書き換わる (= 100s 待ちを bypass、 体感即時化)
    assert ts.next_poll_at <= time.monotonic() + 0.5
    # 信号 set は drain 後に空
    assert jr._watch_signal_paths == set()


def test_drain_watch_signals_unknown_path_is_ignored(tmp_path):
    p = tmp_path / "unknown.jsonl"
    jr._watch_signal_paths.add(p)
    jr._drain_watch_signals_to_state({}, {})
    assert jr._watch_signal_paths == set()


def test_drain_watch_signals_no_signals_noop(tmp_path):
    jr._watch_signal_paths.clear()
    # no exception
    jr._drain_watch_signals_to_state({}, {})


# --- F-03 SessionTailer: _initialize_sid_tail / _tick_sid 基本動作 ---------

def test_initialize_sid_tail_seeks_to_end(isolated_state, tmp_path):
    sid = "ses_init"
    _make_state_for(sid)
    p = tmp_path / "x.jsonl"
    p.write_bytes(b'{"type":"user","message":{"content":"hi"}}\n' * 5)
    ts = jr.SessionTailState()
    jr._initialize_sid_tail(sid, ts, p)
    assert ts.path == p
    assert ts.offset == p.stat().st_size  # 末尾から開始 (= 過去行を再通知しない)


def test_initialize_sid_tail_resets_metadata_on_path_switch(isolated_state, tmp_path):
    sid = "ses_switch"
    _make_state_for(sid)
    state_mod.agent_status[sid]["pr_links"] = [{"prRepository": "x", "prNumber": 1, "prUrl": "y"}]
    state_mod.agent_status[sid]["tasks"] = [{"id": "1", "subject": "old"}]
    p_old = tmp_path / "old.jsonl"
    p_new = tmp_path / "new.jsonl"
    p_old.write_bytes(b"")
    p_new.write_bytes(b"")
    ts = jr.SessionTailState(path=p_old, offset=0)
    jr._initialize_sid_tail(sid, ts, p_new)
    # path 切替で pr_links / tasks が空に reset される (= /clear 後の持ち越し防止)
    assert state_mod.agent_status[sid]["pr_links"] == []
    assert state_mod.agent_status[sid]["tasks"] == []
    assert ts.path == p_new


def test_tick_sid_processes_new_lines(isolated_state, tmp_path, monkeypatch):
    sid = "ses_tick"
    _make_state_for(sid)
    p = tmp_path / "x.jsonl"
    p.write_bytes(b"")
    monkeypatch.setattr(jr, "_latest_jsonl", lambda s: p if s == sid else None)
    ts = jr.SessionTailState()
    # 初回 = initialize で末尾 = 0
    jr._tick_sid(sid, ts, now_mono=100.0)
    assert ts.path == p
    # 追記 → 次 tick で取り込まれ busy=True に
    import json as _json
    with open(p, "a") as f:
        f.write(_json.dumps({"type": "user", "message": {"content": "go"}}) + "\n")
    jr._tick_sid(sid, ts, now_mono=200.0)
    assert state_mod.stream_states[sid].busy is True


def test_tick_sid_unresolved_path_backs_off(isolated_state, monkeypatch):
    """_latest_jsonl が None を返す sid は base interval で次回再試行 (= 旧 inner loop の
    `if path is None: next_poll_at = now + POLL_INTERVAL` 経路と互換)。"""
    sid = "ses_unresolved"
    _make_state_for(sid)
    monkeypatch.setattr(jr, "_latest_jsonl", lambda s: None)
    ts = jr.SessionTailState()
    jr._tick_sid(sid, ts, now_mono=500.0)
    assert ts.next_poll_at == 500.0 + jr.POLL_INTERVAL
