// 表示を時系列 (= ts、 epoch ms) で安定ソートする純粋関数。
//
// メッセージは配列末尾 append で溜まる。 GET 履歴取り込み / SSE replay / 遅延到着では
// **古いメッセージが末尾に積まれる**ので、 配列位置 = 時系列 ではない。
//
// この「配列位置 ≠ 時系列」 が 2 つの症状を生んでいた (= 2026-07-27 中抜け根治):
//   1. 順序がバラバラに見える (= 表示をソートして解決済、 2026-07-22)
//   2. **中抜け**: 表示は末尾 DISPLAY_LIMIT 件に絞られるが、 その「末尾」 が配列位置基準
//      だったため、 位置の先頭に居る cache 由来の**新しい**メッセージが窓外に落ちて消えた。
//      → 窓を切る前にここでソートし、 「時間の最新 N 件」 を選ぶようにした (= ChatPanel)。
//
// ts を持たないメッセージ (= 楽観バブル確定前 / 一部 system marker / __loading__ placeholder)
// は直前の実効キーを継いで時系列上の隣に留め、 元 index を tiebreak にして stable にする
// (= 同 ts の相対順維持)。
export function sortByTs(msgs) {
  let carry = -Infinity
  const keyed = msgs.map((m, i) => {
    const t = typeof m.ts === 'number' ? m.ts : null
    if (t != null) carry = t
    return { m, i, key: t != null ? t : carry }
  })
  keyed.sort((a, b) => (a.key - b.key) || (a.i - b.i))
  return keyed.map((x) => x.m)
}
