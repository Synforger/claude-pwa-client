// 本文の上の指とホイールで字の大きさを変える時の計算 (= 画面から切り離した純関数)。 倍率の値そのもの
// (= 上限・下限・端末に覚える口) は state/textZoom.js。

// Ctrl/⌘ + ホイール (= トラックパッドのつまむ動きも、 ブラウザは ctrlKey 付きの wheel で渡す) の 1 回で
// 掛ける倍率。 動かした量からの換算は d3-zoom の既定 (= 2 の (-deltaY × 0.002 × 10) 乗) をそのまま使う。
// 0.002 は deltaMode が画素の時、 行の時は 0.05、 頁の時は 1 (= d3-zoom の defaultWheelDelta)。
const WHEEL_UNIT = [0.002, 0.05, 1]
const WHEEL_GAIN = 10

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
