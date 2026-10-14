// 入力欄の寸法の計算 (= DOM に触らない純粋な関数だけ。 測るのは ChatInput 側)。
//
// 入力欄は打った分だけ伸び、 上限の行数で止まって中をスクロールする。 上限は 2 つ:
//   - 畳んだ時: INPUT_FOLDED_LINES 行 (= 上のメッセージを読みながら打てる高さ)
//   - 広げた時: INPUT_OPEN_LINES 行 (= 長く書いた分を見渡す高さ)
// 畳んだ時の上限を超えると、 上端に開閉のボタンが出る。

export const INPUT_FOLDED_LINES = 3
export const INPUT_OPEN_LINES = 6

// textarea の高さの上限 (= border-box の px)。
export function lineCap({ lineHeight, padY, borderY }, maxLines) {
  return lineHeight * maxLines + padY + borderY
}

// textarea の高さを決める。
//   content = 中身を全部見せるのに要る高さ / natural = 高さを指定しない時の高さ (= 隣のボタンの列が決める)
// height が null の時は高さを指定しない (= natural のまま)。
export function fitHeight({ content, natural, cap }) {
  const overflowing = content > cap
  const wanted = Math.min(content, cap)
  return { height: wanted > natural ? wanted : null, overflowing }
}
