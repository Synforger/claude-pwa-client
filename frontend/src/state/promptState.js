// tmux pane の「入力待ち」 状態を per-sid で保持する store。
//
// backend の prompt_detector_loop が publish する `type === "prompt_state"` event を
// processStreamEvent から流し込む。 ChatPanel が useSyncExternalStore で subscribe して
// チャット入力欄直上の banner UI を描画する。
//
// wire:
//   event.type === "prompt_state" (backend/terminal/prompt_detector_loop.py)
//     { sid, state: "active"|"tui"|"inline_tui"|"text_prompt"|"idle",
//       category, excerpt, bypass_mode_visible, reason }
//
// state field 値は文字列でそのまま backend の enum と 1:1 対応させる (= mapping なし)。

import { createStore } from './_store.js'

const INITIAL = {
  // { [sid]: { state, category, excerpt, bypassModeVisible, reason, receivedAt } }
  bySid: {},
}

const store = createStore(INITIAL, { name: 'promptState' })

export const getSnapshot = () => store.getSnapshot()
export const subscribe = (listener) => store.subscribe(listener)

// backend event → store update。 processStreamEvent から呼ばれる。
export function ingestPromptStateEvent(event) {
  if (!event || event.type !== 'prompt_state' || !event.sid) return
  const entry = {
    state: event.state || 'active',
    category: event.category || null,
    excerpt: event.excerpt || '',
    bypassModeVisible: !!event.bypass_mode_visible,
    reason: event.reason || '',
    // Phase 4a: quick-reply UI 用 field
    inputMode: event.input_mode || 'none',
    options: Array.isArray(event.options) ? event.options : [],
    keyRequiresEnter: !!event.key_requires_enter,
    receivedAt: Date.now(),
  }
  // 「回答入力中」 等の派生 UI 状態はここでは持たない。 Type something 選択中か等は
  // consumer (= PromptReplyControls) が excerpt から都度導出する (= client local flag は
  // タップ以外の経路 = ↑↓ / 端末直叩き で pane とズレる、 2026-07-06 実機で 2 回破綻)。
  store.setState(prev => ({
    ...prev,
    bySid: { ...prev.bySid, [event.sid]: entry },
  }))
}

// session close 時に呼ぶ (= tab を消したら chip も消す)。
export function clearPromptState(sid) {
  store.setState(prev => {
    if (!(sid in prev.bySid)) return prev
    const next = { ...prev.bySid }
    delete next[sid]
    return { ...prev, bySid: next }
  })
}

// 便利 selector: active sid の entry を返す。 なければ null。
export function selectFor(snapshot, sid) {
  if (!snapshot || !sid) return null
  return snapshot.bySid[sid] || null
}
