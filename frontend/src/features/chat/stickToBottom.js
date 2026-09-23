// チャットが最下端に「張り付いている」 かの判定 (= use-stick-to-bottom と同じ決まり)。
//
// 張り付きが外れるのは、 ユーザが上へスクロールした時だけ (= scrollTop が前回より減った)。
// 最下端からの距離では外さない: 最下端へ送った直後に中身が伸びる (= Markdown / コードの色付け /
// 画像 / 遅れて届く履歴) と、 ユーザが何もしなくても距離が開く。 距離で外すと、 それを
// 「ユーザが離れた」 と誤判定して追従が止まり、 開いた時や ↓ ボタンで途中に止まる。
// 最下端付近まで戻れば (= ユーザが下へスクロールした) 張り付きに戻す。

// 「最下端に居る」 とみなす余白 (= px)。 指の振動と iOS のバウンドを吸収する。
export const AT_BOTTOM_THRESHOLD_PX = 30

// 戻り値: 次の張り付き状態 (= true なら中身が伸びた時に最下端へ送り続ける)。
export function nextStuck({ stuck, prevTop, top, scrollHeight, clientHeight }) {
  const distance = scrollHeight - top - clientHeight
  if (distance <= AT_BOTTOM_THRESHOLD_PX) return true
  // 1px 未満の揺れ (= 小数 scrollTop の丸め) は上スクロールとみなさない。
  if (top < prevTop - 1) return false
  return stuck
}
