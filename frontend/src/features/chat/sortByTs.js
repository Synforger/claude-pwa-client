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
  // carry は「直前までに見た最大 ts」 (= 単調増加)。 直前要素の生 ts をそのまま継ぐと、
  // 配列順が時系列とズレている場面 (= 履歴 replay で古い行が末尾に積まれた直後) に、
  // ts を持たない**新しい** bubble が古いキーを継いで過去へ沈み、 表示窓 (= 末尾
  // DISPLAY_LIMIT 件) の外に落ちて消える (= 2026-07-27 「送信した瞬間に消える」 の増幅要因)。
  // 最大値を継げば、 ts 無し bubble が「今まで見た中で最も新しい位置」 より前に沈むことは
  // 構造的に起きない。 ts を持つ message の相対順は従来通り ts 昇順で不変。
  let carry = -Infinity
  const keyed = msgs.map((m, i) => {
    const t = typeof m.ts === 'number' ? m.ts : null
    if (t != null && t > carry) carry = t
    return { m, i, key: t != null ? t : carry }
  })
  keyed.sort((a, b) => (a.key - b.key) || (a.i - b.i))
  return keyed.map((x) => x.m)
}
