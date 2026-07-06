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
  // { [sid]: true } — Type something (= AskUserQuestion の自由記述 option) を選んだ後の
  // 「回答入力中」 flag (= client local)。 立っている間、 banner は数字ボタンを消して
  // 「下の欄から送信」 表示に切り替える (= 数字タップが text 入力に化けるのを防ぐ、
  // 2026-07-06 実害: 44 / 445 が回答として飛んだ)。 dialog が閉じた遷移 (= 待ち系以外の
  // state 到着) で自動クリア。
  typingAnswer: {},
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
  store.setState(prev => {
    const next = { ...prev, bySid: { ...prev.bySid, [event.sid]: entry } }
    // 待ち系以外 (= active / idle / tui) への遷移 = dialog が閉じた。 回答入力中 flag を
    // 自動で下ろす (= 次の質問で古い flag が残らない)。
    const waiting = entry.state === 'inline_tui' || entry.state === 'text_prompt'
    if (!waiting && prev.typingAnswer[event.sid]) {
      const ta = { ...prev.typingAnswer }
      delete ta[event.sid]
      next.typingAnswer = ta
    }
    return next
  })
}

// Type something 選択直後に PromptReplyControls から呼ぶ (= client local の UI mode)。
export function setTypingAnswer(sid, on) {
  if (!sid) return
  store.setState(prev => {
    if (!!prev.typingAnswer[sid] === !!on) return prev
    const ta = { ...prev.typingAnswer }
    if (on) ta[sid] = true
    else delete ta[sid]
    return { ...prev, typingAnswer: ta }
  })
}

export function selectTypingAnswer(snapshot, sid) {
  return !!(snapshot && sid && snapshot.typingAnswer[sid])
}

// session close 時に呼ぶ (= tab を消したら chip も消す)。
export function clearPromptState(sid) {
  store.setState(prev => {
    if (!(sid in prev.bySid) && !(sid in prev.typingAnswer)) return prev
    const next = { ...prev.bySid }
    delete next[sid]
    const ta = { ...prev.typingAnswer }
    delete ta[sid]
    return { ...prev, bySid: next, typingAnswer: ta }
  })
}

// 便利 selector: active sid の entry を返す。 なければ null。
export function selectFor(snapshot, sid) {
  if (!snapshot || !sid) return null
  return snapshot.bySid[sid] || null
}
