import { REPLAY_SKEW_TOLERANCE_MS } from '../../constants.js'

// event が bubble より過去か (= 履歴 replay 由来で、 この未確定 bubble の確定 / 中身たり得ないか)。
//
// GET 履歴 replay は古い user_message / assistant を流すので、 これを見ないと
//   - 送信直後の楽観バブルが大昔の発話に上書きされて消える
//   - 推論中の空 placeholder に大昔の応答が入る
// という食い潰しが起きる (= 2026-07-26 実機報告の根治)。 未確定バブルを確定できるのは
// **その送信より後**に生まれた event だけ、 が物理。
//
// 判定材料が欠けてる時 (= どちらかの ts が無い) は「過去でない」 に倒して既存の近似 match を
// 活かす (= ts は 2026-07-22 導入なので旧 cache の bubble には無い)。
export function isStaleFor(eventTs, bubbleTs) {
  if (typeof eventTs !== 'number' || typeof bubbleTs !== 'number') return false
  return eventTs < bubbleTs - REPLAY_SKEW_TOLERANCE_MS
}
