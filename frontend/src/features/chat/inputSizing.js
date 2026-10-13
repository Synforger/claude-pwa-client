// 入力欄の寸法の計算 (= DOM に触らない純粋な関数だけ。 測るのは ChatInput 側)。
//
// 入力欄は 2 つの大きさを持つ:
//   - 畳んだ時: 打った分だけ伸び、 INPUT_MAX_LINES 行で止まって中をスクロールする
//   - 広げた時: チャットの領域のうち、 今 見えている範囲いっぱい (= 画面キーボードの上まで)

// 畳んだ時に伸びる上限の行数。 これを超えると開閉のボタンが出る。
export const INPUT_MAX_LINES = 6

// 畳んだ時の textarea の高さの上限 (= border-box の px)。
export function collapsedCap({ lineHeight, padY, borderY }, maxLines = INPUT_MAX_LINES) {
  return lineHeight * maxLines + padY + borderY
}

// 畳んだ時の textarea の高さを決める。
//   content = 中身を全部見せるのに要る高さ / natural = 高さを指定しない時の高さ (= 隣のボタンの列が決める)
// height が null の時は高さを指定しない (= natural のまま)。
export function fitHeight({ content, natural, cap }) {
  const overflowing = content > cap
  const wanted = Math.min(content, cap)
  return { height: wanted > natural ? wanted : null, overflowing }
}

// 広げた時の入力欄の矩形 (= position: fixed 用、 layout viewport の座標)。
//   areaTop  = チャットの領域の上端
//   slot     = 畳んだ時に入力欄が居る場所 (= left / width / bottom / height)
//   viewport = 今 見えている範囲 (= visualViewport の offsetTop と height)
// 上端は「チャットの領域」 と「見えている範囲」 の下にある方、 下端は上にある方。 画面キーボードが
// 出ている間は見えている範囲が縮むので、 下端はキーボードの上で止まる。 畳んだ時より小さくはしない。
export function expandedRect({ areaTop, slot, viewport }) {
  const bottom = Math.min(slot.bottom, viewport.top + viewport.height)
  const top = Math.max(areaTop, viewport.top)
  const height = Math.max(bottom - top, slot.height)
  return { top: bottom - height, left: slot.left, width: slot.width, height }
}
