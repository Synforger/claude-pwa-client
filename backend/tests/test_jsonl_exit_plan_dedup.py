"""ExitPlanMode 二重起動 dedup の bounded set 検査 (= backend-F-14)。

旧版は a["pending_plan"]["tool_use_id"] と一致で skip する gate のみで、 pending_plan
が clear (= ユーザ承認 / 別 plan で上書き) された後に同 tool_id が再到着すると capture
を二重起動する穴があった。 OrderedDict + maxlen 64 ベースに切替えたことを担保。
"""
from backend.jsonl import session_status as ss


def test_remember_exit_plan_first_time_returns_true():
    ss._processed_exit_plan_ids.clear()
    assert ss._remember_exit_plan("ses_a", "tool_1") is True


def test_remember_exit_plan_duplicate_returns_false():
    ss._processed_exit_plan_ids.clear()
    ss._remember_exit_plan("ses_a", "tool_1")
    assert ss._remember_exit_plan("ses_a", "tool_1") is False


def test_remember_exit_plan_per_sid_isolated():
    ss._processed_exit_plan_ids.clear()
    ss._remember_exit_plan("ses_a", "tool_1")
    # 別 sid なら新規扱い
    assert ss._remember_exit_plan("ses_b", "tool_1") is True


def test_remember_exit_plan_bounded_evicts_oldest():
    ss._processed_exit_plan_ids.clear()
    # 上限 + 5 個記録
    for i in range(ss._PROCESSED_EXIT_PLAN_LIMIT + 5):
        ss._remember_exit_plan("ses_a", f"tool_{i}")
    seen = ss._processed_exit_plan_ids["ses_a"]
    # サイズが maxlen で頭打ち
    assert len(seen) == ss._PROCESSED_EXIT_PLAN_LIMIT
    # 最古 (= tool_0..tool_4) は押し出されていて、 再到着で True を返す
    assert ss._remember_exit_plan("ses_a", "tool_0") is True
    # 最新 (= tool_LIMIT+4) はまだ残っていて False
    assert ss._remember_exit_plan("ses_a", f"tool_{ss._PROCESSED_EXIT_PLAN_LIMIT + 4}") is False


def test_remember_exit_plan_empty_id_passes_through():
    """tool_use_id が無い (= 空文字 / None) 行は弾けないので素通し (= 旧挙動)。"""
    ss._processed_exit_plan_ids.clear()
    assert ss._remember_exit_plan("ses_a", "") is True
    assert ss._remember_exit_plan("ses_a", None) is True  # type: ignore[arg-type]


def test_cleanup_orphan_exit_plan_ids_removes_stale(isolated_state):
    state = isolated_state
    ss._processed_exit_plan_ids.clear()
    # sessions_meta に登録の無い sid を 2 つ + 登録ありの sid を 1 つ
    ss._remember_exit_plan("ses_orphan_1", "t1")
    ss._remember_exit_plan("ses_orphan_2", "t2")
    # 登録済 sid を 1 つ用意 (= 残す)
    sid_alive = next(iter(state.sessions_meta), None)
    if sid_alive is None:
        # conftest._TEST_CONFIG ベースで 1 session 立ってる想定だが、 無ければ skip
        return
    ss._remember_exit_plan(sid_alive, "t3")
    removed = ss.cleanup_orphan_exit_plan_ids()
    assert removed == 2
    assert "ses_orphan_1" not in ss._processed_exit_plan_ids
    assert "ses_orphan_2" not in ss._processed_exit_plan_ids
    assert sid_alive in ss._processed_exit_plan_ids


def test_exit_plan_dedup_survives_pending_plan_clear(isolated_state):
    """pending_plan が clear された後の同 tool_id 再到着でも capture を再起動しない
    (= F-14 の本来意図)。 mutate_agent_status 経由で 2 回行を流し込んで挙動を確認。"""
    import asyncio
    state = isolated_state
    ss._processed_exit_plan_ids.clear()
    sid = "ses_plan"
    state.agent_status[sid] = {
        "pending_plan": None, "plan_mode": False,
        "current_tool": None, "todos": None, "subagent": None,
        "pending_question": None, "model": "", "ctx_pct": 0, "ctx_window": 1_000_000,
        "tasks": [], "pr_links": [],
    }
    import backend.state as state_mod
    state.stream_states[sid] = state_mod.StreamState(agent_id="a")

    # capture_plan_choices が tmux を叩かないよう coroutine をスタブ化
    captured: list[str] = []

    async def fake_capture(session_id, tool_id):
        captured.append(tool_id)

    import backend.jsonl.session_status as ss_mod
    orig = ss_mod.capture_plan_choices
    ss_mod.capture_plan_choices = fake_capture
    try:
        line = {
            "type": "assistant",
            "message": {
                "role": "assistant",
                "content": [{
                    "type": "tool_use", "name": "ExitPlanMode",
                    "id": "exit_tool_id", "input": {"plan": "p"},
                }],
            },
        }
        # 1 回目: 新規 = capture 起動
        async def _run():
            ss.mutate_agent_status(sid, line)
            # ユーザ承認 → pending_plan を clear する simulation
            state.agent_status[sid]["pending_plan"] = None
            # 2 回目: 同 tool_id 再到着 (= path 切替 race 等)。 bounded set で skip 期待
            ss.mutate_agent_status(sid, line)

        asyncio.run(_run())
        # capture は 1 回だけ起動 (= 2 回目は dedup で skip)
        assert captured.count("exit_tool_id") == 1
    finally:
        ss_mod.capture_plan_choices = orig
