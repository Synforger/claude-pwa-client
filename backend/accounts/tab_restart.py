"""Stopping the claude of a tab and clearing what it left in the tab's status: the two halves of a restart, which moving a
tab to another account does too.

Used by `routes/sessions.py` (= restart) and `accounts/account_move.py` (= moving a tab to another account).
"""
from __future__ import annotations

import logging

from backend._common import state
from backend.jsonl import history as session_history
import backend.jsonl.jsonl_watcher as jsonl_watcher
from backend.terminal.runner import pty_sessions
from backend.terminal.tab_stop import stop_tab

logger = logging.getLogger(__name__)


async def stop_tab_claude(session_id: str) -> None:
    """Stop the claude of a tab and its pane, keeping the tab itself (= the first half of a restart). Returns once
    that claude has ended, so the next one never runs beside it."""
    # kill する前に現 claude_sid を履歴に積む (= 事故時の復旧源、 pwa_sid あたり最新 3 件保持)。
    # binding が落ちてる場合は no-op になる (= record_end が None を弾く)。
    try:
        cur = jsonl_watcher.get_jsonl_for(session_id)
        if cur is not None:
            cur_sid = cur.stem  # claude jsonl ファイル名 = claude_sid
            session_history.record_end(session_id, cur_sid, jsonl_path=str(cur))
    except Exception:
        # 履歴記録の失敗は復旧経路を 1 本失うので、 debug ではなく warning で残す
        # (= 2026-06-22 silent-failure sweep)。
        logger.warning("session_history record failed for %s", session_id, exc_info=True)
    # kill 経路は delete_session と同じだが、 sessions_meta は維持して即 spawn し直す
    try:
        await stop_tab(session_id)
        pty_sessions.pop(session_id, None)
        jsonl_watcher.unregister(session_id)
    except Exception:
        # kill 失敗 = claude プロセスが残ったまま spawn する経路に進み二重起動の race を起こす
        # 可能性がある。 warning で残す (= 2026-06-22)。
        logger.warning("restart kill phase failed for %s", session_id, exc_info=True)


async def reset_tab_status(session_id: str) -> None:
    """Forget what the stopped claude left in a tab's status, so the next one starts clean."""
    # agent_status の進行中フラグと蓄積 state をリセット (= 新プロセス = 新 claude_sid で
    # 過去 JSONL の集約結果 (= tasks / todos / current_tool 等) を持ち越さない)。
    # SessionState.lock 経由で複数 mutate を 1 critical section に束ねる (= backend-F-07)。
    # 注意: この lock を取るのは restart のこの区間だけで、 常時系の mutate 経路
    # (= mutate_agent_status 等) は lock を取らない。 全経路が
    # 単一 event loop 上の同期処理 (= await を跨がない dict 書換) なので dict 破壊は起きない。
    # lock の意味は「reset の複数 field 書換を 1 まとまりにする」 ことだけで、 mutate 経路との
    # 排他保証と読まないこと。
    # 2026-07-03: tasks / todos / model / ctx_pct / budget_* / mode / permission_mode
    # を追加リセット。 restart は「文脈 + プロセスリセット」 なので、 前 claude 由来の状態は
    # 全て消す。 新 JSONL からの task_reminder / model 通知で正しい値に埋め直す。
    sess = state.get_session(session_id)
    if sess is not None:
        async with sess.lock:
            a = sess.status
            a["current_tool"] = None
            a["pending_plan"] = None
            a["subagent"] = None
            a["plan_mode"] = False
            a["tasks"] = []
            a["todos"] = []
            a["model"] = ""
            a["ctx_pct"] = 0
            a["budget_used"] = None
            a["budget_total"] = None
            a["budget_remaining"] = None
            a["mode"] = ""
            a["permission_mode"] = ""
            # 新プロセス = 過去の Stop 意思は無効化 (= 残ったまま sticky だと新 turn が永久に
            # busy=false に強制されて停止ボタンが立たない逆方向のバグになる)。
            sess.stream.user_stopped = False
            # 終了を停止と対称化 (= busy 系を同期でリセット)。 restart は user_stopped を
            # False に戻すので、 busy / pane_working / queued_sends を落とさないと overview
            # busy (= st.busy OR pane_working) が残り、 「推論中に終了 → 青丸残留」 になる。
            # 旧来は monitor の path 切替再計算 / detector poll の非同期自己回復頼みで、
            # それが発火し損ねると永久残留していた。
            sess.stream.busy = False
            sess.stream.pane_working = False
            sess.stream.queued_sends = 0
            sess.stream.status_event.set()
