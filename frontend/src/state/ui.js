// UI 局所 state (= state-trace.md § 5)。 overlay 11 個 + scroll 4 ref + keyboard 5 modifier +
// viewModes + desktopOpen + extensionOpen + planOpen + storageWarnDismissed。 localStorage 永続化対象は viewModes
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
    extensionOpen: null,  // 開いている拡張の id (= null で全部畳む)
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

// チャットの上に帯で出る枠 (= 画面共有 / 拡張)。 同時に開くのは 1 つだけで、 1 つを開くと他は閉じる
// (= 帯が縦に積み重なるとチャットが押し出される)。 閉じた値は各 key の初期値 (= false / null)。
const BAND_OVERLAYS = ['desktopOpen', 'extensionOpen']

export function setOverlay(key, value) {
  store.setState(prev => {
    if (prev.overlays[key] === value) return prev
    const overlays = { ...prev.overlays, [key]: value }
    if (value && BAND_OVERLAYS.includes(key)) {
      for (const other of BAND_OVERLAYS) {
        if (other !== key) overlays[other] = INITIAL.overlays[other]
      }
    }
    return { ...prev, overlays }
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

// Phase J-12 (= 2026-06-29、 audit-w2-residue B sweep): flashingKeys 用 add/remove。
// useKeyboardState の flash timer 経路で使う (= pressedKeys と symmetric API)。
export function addFlashingKey(key) {
  store.setState(prev => {
    if (prev.keyboard.flashingKeys.has(key)) return prev
    const next = new Set(prev.keyboard.flashingKeys); next.add(key)
    return { ...prev, keyboard: { ...prev.keyboard, flashingKeys: next } }
  })
}
export function removeFlashingKey(key) {
  store.setState(prev => {
    if (!prev.keyboard.flashingKeys.has(key)) return prev
    const next = new Set(prev.keyboard.flashingKeys); next.delete(key)
    return { ...prev, keyboard: { ...prev.keyboard, flashingKeys: next } }
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
