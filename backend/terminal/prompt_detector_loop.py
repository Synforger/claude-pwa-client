"""prompt_detector を全 tmux session に対して 500ms 周期で走らせる background loop。

Phase 1 で作った pure ``analyze()`` を、 実 tmux session lifecycle と接続する層。

責務:
    - 生きてる tmux session を列挙し、 各 pane で ``alternate_on`` + ``capture-pane``
      snapshot を取る
    - ``analyze()`` に食わせて Verdict を得る
    - 前回状態と比較し、 遷移した時だけ ``jsonl_event_broadcaster`` に
      ``prompt_state`` event を publish (= 連発抑制)
    - 遷移先が「入力待ち」 系 (= TEXT_PROMPT / INLINE_TUI / TUI) なら Web Push 発火
    - session 消滅時に state を掃除

PWA は SSE 経路で ``prompt_state`` event を受けて chip UI を更新する (= Phase 3)。

なぜ既存 ``monitor_all_sessions_loop`` と分離するか:
    - あちらは JSONL tail (= claude の応答) を追う責務、 tmux poll (= 出力画面)
      とは別 subsystem
    - poll 周期が違う (500ms vs 変動 400ms-2s)、 失敗時 quarantine 方針も違う
    - 障害を独立させる (= 片方の bug が両方の subsystem を落とさない)
"""
from __future__ import annotations

import asyncio
import logging

from backend.core.push import broadcast_push
from backend.state import jsonl_event_broadcaster, sessions_meta
from backend.terminal.prompt_detector import (
    DetectorConfig,
    DetectorState,
    PromptState,
    TailSnapshot,
    Verdict,
    analyze,
)
from backend.terminal.runner import (
    capture_pane_plain_tail,
    get_pane_alternate_on,
    has_tmux_session,
)

logger = logging.getLogger(__name__)

# poll 周期。 tmux コマンドは軽量、 実測で 10 pane / 200ms 以下想定なので 500ms で
# 余裕を持たせる。 頻度上げれば遷移遅延が減るが、 idle threshold (2s / 5s) 相対で
# 500ms は十分細かい。
POLL_INTERVAL_SEC: float = 0.5

# Push を発火する遷移先の集合。 IDLE や ACTIVE / TUI 復帰 (= 元に戻っただけ) は push しない。
_PUSH_TRIGGER_STATES: frozenset[PromptState] = frozenset(
    {PromptState.TEXT_PROMPT, PromptState.INLINE_TUI}
)

# 全 loop 共有の per-session detector state。 module 変数にしてるのは
# ``note_user_input`` を route から直呼びできるようにするため (= grace period を
# route 側でその場で反映)。
_detector_states: dict[str, DetectorState] = {}
_config = DetectorConfig()


def note_user_input(session_id: str) -> None:
    """user が tmux にキー送信した瞬間を記録する (= tier C の grace period 用)。

    ``terminal/routes.py`` の pty_send 系 endpoint が ``tmux_send_keys`` を叩いた
    直後に呼ぶ。 backend の内部再送 (= confirm の Enter 救済) では呼ばない (= あちらは
    「ユーザが入力した」 わけではないので grace を掛けると同じ prompt を隠しかねない)。
    """
    state = _detector_states.get(session_id)
    if state is None:
        # まだ detector が初回 snapshot を撮ってないケース。 loop の次 tick で state
        # が作られるので、 先回りで作っておく (= 直後に来る tick の grace を活かす)。
        state = DetectorState()
        _detector_states[session_id] = state
    loop = asyncio.get_running_loop()
    state.record_input_sent(loop.time())


def _build_event(sid: str, verdict: Verdict) -> dict:
    # `type` field は既存の processStreamEvent 側と整合させる (= 他 event と同じ規約)。
    return {
        "type": "prompt_state",
        "sid": sid,
        "state": verdict.state.value,
        "category": verdict.category.value if verdict.category else None,
        "excerpt": verdict.excerpt,
        "bypass_mode_visible": verdict.bypass_mode_visible,
        "reason": verdict.reason,
        # PWA quick-reply UI 用 (= Phase 4a)
        "input_mode": verdict.input_mode.value,
        "options": list(verdict.options),
        "key_requires_enter": verdict.key_requires_enter,
    }


def _push_title_for(verdict: Verdict) -> tuple[str, str] | None:
    """Web Push の (title, body) を verdict から作る。 push 対象外なら None。"""
    if verdict.state not in _PUSH_TRIGGER_STATES:
        return None
    if verdict.state == PromptState.INLINE_TUI:
        title = "⌨ Selection prompt"
        body = verdict.excerpt or "TUI is waiting for a choice."
    else:  # TEXT_PROMPT
        cat = verdict.category.value if verdict.category else "prompt"
        title = f"⏸ Waiting: {cat}"
        body = verdict.excerpt or "Terminal is waiting for input."
    return title, body


async def _tick_one(sid: str) -> None:
    """1 session 分の poll + analyze + event/push 発火。 例外は呼び出し側で catch。"""
    if not has_tmux_session(sid):
        # session 消えてたら detector state も掃除して抜ける
        _detector_states.pop(sid, None)
        return

    alt = get_pane_alternate_on(sid)
    if alt is None:
        # tmux が返さない (= 一時的に応答遅延) 場合は「不明」 として False 扱い
        alt = False
    tail = capture_pane_plain_tail(sid) or ""
    now = asyncio.get_running_loop().time()
    snapshot = TailSnapshot(alternate_on=alt, tail_text=tail, now_sec=now)

    state = _detector_states.setdefault(sid, DetectorState())
    prev_state = state.current_state
    verdict = analyze(snapshot, state, _config)

    if not state.seeded:
        # 初回 tick: 既に「入力待ち」 状態で backend が起動しただけかもしれないので
        # 「発生 event」 として扱わない。 現状態を追認して押し黙る。 SSE / push
        # とも発火しない。 次 tick 以降が本番。 (= 2026-07-05 hotfix: restart 直後に
        # 全 session ぶんの push が発火する現象への対処)
        state.current_state = verdict.state
        state.seeded = True
        return

    if verdict.state == prev_state:
        return  # 遷移なし = 沈黙 (= 連発 push 抑制)
    state.current_state = verdict.state

    # SSE 経路 (= chip UI 用): 全遷移を流す
    jsonl_event_broadcaster.publish(sid, _build_event(sid, verdict))

    # Web Push: 「入力待ち」 系の遷移だけ。 元に戻る (= ACTIVE) 遷移では push しない。
    push_pair = _push_title_for(verdict)
    if push_pair is not None:
        title, body = push_pair
        # broadcast_push は async だが fire-and-forget (= loop を止めない)
        asyncio.create_task(broadcast_push(body, title, sid))


async def prompt_detector_loop() -> None:
    """全 session を巡回する main loop。 ``main.py`` の startup で create_task で起動。

    起動失敗 (= tmux 不在 / helper が None) は次 tick で復帰試行。 個別 session の
    例外は log だけして他 session を継続 (= 1 pane の misbehavior が全体を止めない)。
    """
    logger.info("prompt_detector_loop started (interval=%.2fs)", POLL_INTERVAL_SEC)
    try:
        while True:
            try:
                await asyncio.sleep(POLL_INTERVAL_SEC)
                # sessions_meta 側で消えた sid の detector state を掃除
                for stale in [s for s in _detector_states if s not in sessions_meta]:
                    _detector_states.pop(stale, None)
                for sid in list(sessions_meta.keys()):
                    try:
                        await _tick_one(sid)
                    except Exception:
                        logger.exception("prompt_detector: tick failed sid=%s", sid)
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("prompt_detector_loop outer iteration failed")
    except asyncio.CancelledError:
        logger.info("prompt_detector_loop cancelled")
        raise
