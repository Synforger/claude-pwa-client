// 文章 (= 📋 のメモと markdown のプレビュー) の字の大きさの倍率 (= 画面から切り離した純関数と、 端末に覚える口)。
//
// 倍率は CSS の zoom で本文に掛ける。 zoom はその倍率で行を組み直すので、 縮めると 1 行に入る字が増え、
// 広げても枠の幅で折り返して横にははみ出さない (= 写真のような拡大ではなく、 字の大きさを変える)。
// 値はメモとプレビューで 1 つ、 端末ごとに覚える (= Mac と iPhone で別の値)。

// これより小さいと字が読めない (= 幅の広い表やコードの全体の形を見るための大きさ)
export const TEXT_ZOOM_MIN = 0.5
// 離して置いた画面でも読める大きさ
export const TEXT_ZOOM_MAX = 2

// Ctrl/⌘ + ホイール (= トラックパッドのつまむ動きも、 ブラウザは ctrlKey 付きの wheel で渡す) の 1 回で
// 掛ける倍率。 動かした量からの換算は d3-zoom の既定 (= 2 の (-deltaY × 0.002 × 10) 乗) をそのまま使う。
// 0.002 は deltaMode が画素の時、 行の時は 0.05、 頁の時は 1 (= d3-zoom の defaultWheelDelta)。
const WHEEL_UNIT = [0.002, 0.05, 1]
const WHEEL_GAIN = 10

const LS_KEY = 'cpc_v2_text_zoom'

export function clampTextZoom(value) {
  return Math.min(TEXT_ZOOM_MAX, Math.max(TEXT_ZOOM_MIN, value))
}

export function wheelFactor(deltaY, deltaMode) {
  return 2 ** (-deltaY * (WHEEL_UNIT[deltaMode] ?? WHEEL_UNIT[0]) * WHEEL_GAIN)
}

// 2 本の指の間隔
export function spread(touches) {
  return Math.hypot(touches[0].clientX - touches[1].clientX, touches[0].clientY - touches[1].clientY)
}

// 倍率を変えた後に送る量。 anchorY (= 指の在る高さ) に見えていた所が、 変えた後も同じ高さに来るように
// する。 組み直しで行の数が変わるので、 本文の中での割合で合わせる。 before / after は本文の
// getBoundingClientRect() の top と height。
export function scrollToKeep(before, after, anchorY) {
  const within = before.height ? (anchorY - before.top) / before.height : 0
  return after.top + within * after.height - anchorY
}

export function loadTextZoom() {
  try {
    const stored = localStorage.getItem(LS_KEY)
    const value = Number(stored)
    if (stored !== null && Number.isFinite(value)) return clampTextZoom(value)
  } catch { /* localStorage 不可 (= private mode 等) は毎回 100% から */ }
  return 1
}

export function saveTextZoom(value) {
  try { localStorage.setItem(LS_KEY, String(value)) } catch { /* 覚えられないだけで、 動きは同じ */ }
}
