// UI 局所 state (= state-trace.md § 5)。 overlay 11 個 + scroll 4 ref + keyboard 5 modifier +
// viewModes + desktopOpen + planOpen + storageWarnDismissed。 localStorage 永続化対象は viewModes
// と unread 関連、 残りは ephemeral と同じく非永続。

import { createStore } from './_store.js'

const INITIAL = {
  overlays: {
    drawer: false,
    menu: false,
    favs: false,
    tasks: false,
    subagents: false,
    subagentsFocus: null,
    previewPath: null,
    treeOpen: null,
    confirmEnd: false,
    confirmStop: false,
    confirmDelete: null,
    desktopOpen: false,
    planOpen: false,
    storageWarnDismissed: false,
  },
  scroll: {
    isAtBottom: true,
    showScrollBtn: false,
    hasNew: false,
  },
  keyboard: {
    pressedKeys: new Set(),
    flashingKeys: new Set(),
    shift: false,
    caps: false,
    ctrl: false,
    opt: false,
    cmd: false,
  },
  viewModes: {},  // { [sid]: 'chat' | 'terminal' }
}

const store = createStore(INITIAL, { name: 'ui' })

export const getSnapshot = () => store.getSnapshot()
export const subscribe = (listener) => store.subscribe(listener)

export function setOverlay(key, value) {
  store.setState(prev => {
    if (prev.overlays[key] === value) return prev
    return { ...prev, overlays: { ...prev.overlays, [key]: value } }
  })
}

export function setScroll(patch) {
  store.setState(prev => ({ ...prev, scroll: { ...prev.scroll, ...patch } }))
}

export function setModifier(name, value) {
  store.setState(prev => {
    if (prev.keyboard[name] === value) return prev
    return { ...prev, keyboard: { ...prev.keyboard, [name]: value } }
  })
}

export function addPressedKey(key) {
  store.setState(prev => {
    if (prev.keyboard.pressedKeys.has(key)) return prev
    const next = new Set(prev.keyboard.pressedKeys); next.add(key)
    return { ...prev, keyboard: { ...prev.keyboard, pressedKeys: next } }
  })
}
export function removePressedKey(key) {
  store.setState(prev => {
    if (!prev.keyboard.pressedKeys.has(key)) return prev
    const next = new Set(prev.keyboard.pressedKeys); next.delete(key)
    return { ...prev, keyboard: { ...prev.keyboard, pressedKeys: next } }
  })
}

export function setViewMode(sid, mode) {
  store.setState(prev => {
    if (prev.viewModes[sid] === mode) return prev
    return { ...prev, viewModes: { ...prev.viewModes, [sid]: mode } }
  })
}

export function hydrate(partial) {
  if (!partial || typeof partial !== 'object') return
  store.setState(prev => ({ ...prev, ...partial }))
}
