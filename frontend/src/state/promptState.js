// tmux pane の「入力待ち」 状態を per-sid で保持する store。
//
// backend の prompt_detector_loop が publish する `type === "prompt_state"` event を
// processStreamEvent から流し込む。 StatusBar / ChatPanel が useSyncExternalStore で
// subscribe して chip UI を描画する。
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
