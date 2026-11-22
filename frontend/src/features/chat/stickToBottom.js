// チャットと票の画面が最下端に「張り付いている」 かの判定 (= use-stick-to-bottom と同じ決まり)。
//
// 張り付きが外れるのは、 ユーザが上へスクロールした時だけ (= scrollTop が前回より減った)。
// 最下端からの距離では外さない: 最下端へ送った直後に中身が伸びる (= Markdown / コードの色付け /
// 画像 / 遅れて届く履歴) と、 ユーザが何もしなくても距離が開く。 距離で外すと、 それを
// 「ユーザが離れた」 と誤判定して追従が止まり、 開いた時や ↓ ボタンで途中に止まる。
// 最下端付近まで戻れば (= ユーザが下へスクロールした) 張り付きに戻す。

// 「最下端に居る」 とみなす余白 (= px)。 指の振動と iOS のバウンドを吸収する。
export const AT_BOTTOM_THRESHOLD_PX = 30

// 最下端へ送った後、 送りが「止まった」 と見なすまでの静かな時間 (= ms)。 送りの出来事がこの間
// 途切れたら止まったとする。 scrollend の polyfill が同じ判定に使う 100ms と同じ値。
export const SCROLL_SETTLE_MS = 100

// 戻り値: 次の張り付き状態 (= true なら中身が伸びた時に最下端へ送り続ける)。
//
// settling = 最下端へ送った直後で、 その前から続いていた動き (= 指で弾いた惰性、 動いている途中の
// 送り) がまだ止まっていない間。 この間の上への動きは、 ユーザが今スクロールした物ではないので、
// 張り付きを外さない (= 外すと、 ↓ を押した直後に残りの惰性で「離れた」 と判定され、 最下端に
// 着かないまま ↓ がまた出る)。
export function nextStuck({ stuck, prevTop, top, scrollHeight, clientHeight, settling = false }) {
  const distance = scrollHeight - top - clientHeight
  if (distance <= AT_BOTTOM_THRESHOLD_PX) return true
  // 1px 未満の揺れ (= 小数 scrollTop の丸め) は上スクロールとみなさない。
  if (top < prevTop - 1) return settling ? stuck : false
  return stuck
}

// 最下端へ一瞬で飛ぶ。 `.messages` は CSS で scroll-behavior: smooth なので、 scrollTop への代入は
// アニメーションになる。 アニメーションの目標は開始時点の最下端に固定され、 途中で中身が伸びると
// 手前で止まり、 送り直すと iOS Safari は途中で打ち切ったり少し戻ったりする (= 2026-09-23 の実機
// 計測で iPhone だけ 100-1,500px 手前に止まっていた)。 自前の追従は behavior: 'instant' で飛ぶ
// (= 指のスクロールには影響しない)。 票の画面も同じ飛び方を使う。
export function jumpToBottom(el) {
  if (typeof el.scrollTo === 'function') {
    el.scrollTo({ top: el.scrollHeight, behavior: 'instant' })
  } else {
    el.scrollTop = el.scrollHeight
  }
}
