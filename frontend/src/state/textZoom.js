// 📋 のメモと markdown のプレビューの字の大きさ (= 倍率。 その端末だけの値で、 1 で 100%)。
//
// 書くのは 2 か所: 本文の上の 2 本の指 / Ctrl・⌘ + ホイール (= _common/useTextZoom.js) と、 設定 (= ⚙) の
// 「文字の大きさ」 の行。 どちらも同じ 1 つの値を読み書きする (= 基準の大きさと拡大の 2 段にしない)。
// localStorage に覚える (= Mac と iPhone で別の値)。
//
// 倍率は CSS の zoom で本文に掛ける。 zoom はその倍率で行を組み直すので、 文は枠の幅で折り返し直す
// (= 写真のような拡大ではなく、 字の大きさを変える)。
import { createStore } from './_store.js'

// これより小さいと字が読めない (= 幅の広い表やコードの全体の形を見るための大きさ)
export const TEXT_ZOOM_MIN = 0.5
// 離して置いた画面でも読める大きさ
export const TEXT_ZOOM_MAX = 2
// 設定の − / ＋ の 1 回 (= 10%)
const STEP = 0.1

const LS_KEY = 'cpc_v2_text_zoom'

export function clampTextZoom(value) {
  return Math.min(TEXT_ZOOM_MAX, Math.max(TEXT_ZOOM_MIN, value))
}

// 設定の − / ＋ (= dir は -1 / +1)。 指で決めた半端な値 (= 141%) からは、 近い 10% の刻みへ寄せてから進む。
export function stepTextZoom(zoom, dir) {
  return clampTextZoom((Math.round(zoom / STEP) + dir) * STEP)
}

function initial() {
  try {
    const stored = localStorage.getItem(LS_KEY)
    const value = Number(stored)
    if (stored !== null && Number.isFinite(value)) return clampTextZoom(value)
  } catch { /* localStorage 不可 (= private mode 等) は毎回 100% から */ }
  return 1
}

const store = createStore({ zoom: initial() }, { name: 'textZoom' })

export const getSnapshot = () => store.getSnapshot()
export const subscribe = (listener) => store.subscribe(listener)

export function setTextZoom(value) {
  const zoom = Math.round(clampTextZoom(Number(value)) * 100) / 100
  if (!Number.isFinite(zoom)) return
  store.setState(prev => (prev.zoom === zoom ? prev : { ...prev, zoom }))
  try { localStorage.setItem(LS_KEY, String(zoom)) } catch { /* 覚えられないだけで、 動きは同じ */ }
}
