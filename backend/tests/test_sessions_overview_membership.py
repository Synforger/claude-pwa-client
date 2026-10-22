"""タブの増減は、 一覧の概要の stream をその場で起こす (= 画面は snapshot のタブの集まりで一覧を合わせる)。

別の端末・子のタブ・エージェントが立てたタブと消したタブは、 誰かの状態が次に変わるまで画面の一覧に
出なかった。 増やす口と消す口が、 その場で全部の接続を起こす。
"""
from __future__ import annotations

import asyncio


def test_a_tab_registered_or_unregistered_wakes_every_overview_connection(isolated_state):
    state = isolated_state

    async def _go():
        first, second = state.sessions_overview.subscribe(), state.sessions_overview.subscribe()
        try:
            meta = state.register_session("agent_a", "a tab")
            assert first.is_set() and second.is_set()
            first.clear()
            second.clear()
            assert state.unregister_session(meta.id) is True
            assert first.is_set() and second.is_set()
            first.clear()
            assert state.unregister_session(meta.id) is False      # nothing left to remove: nothing to say
            assert not first.is_set()
        finally:
            state.sessions_overview.unsubscribe(first)
            state.sessions_overview.unsubscribe(second)

    asyncio.run(_go())
