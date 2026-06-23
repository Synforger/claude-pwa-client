import { generateId } from '../../utils/id.js'
import { MAX_MESSAGES } from '../../constants.js'

// JSONL の user_message イベントを現在の messages 配列に統合する純粋関数。
//
// sendMessage が即時挿入する「楽観 user バブル」 と、 後から claude の JSONL 経由で来る
// user_message が二重表示にならないよう調停する。 返り値は新しい messages 配列。
// 変更が無い場合は受け取った cur をそのまま返す (= 呼び側が参照比較で再 render を抑制)。
//
// 優先順:
//   1. 既知 uuid → 何もしない
//   2. 添付付き (= "[添付ファイル: /path]" を含む) → fileNames/imageUrls 持ちの楽観と置換
//   3. text 完全一致の楽観 → uuid 補完して optimistic を外す
//   4. 完全一致は無いが、 未確定楽観のテキストが eventText の部分文字列
//      (= claude が推論中の連投を 1 プロンプトに結合して受領した兆候) → その楽観を confirm し、
//      結合された JSONL バブルは追加しない (= 3 つ目の結合バブルを出さない)
//   5. どれにも該当しない (= replay / 純粋な新規発話) → user バブルを新規追加
export function reconcileUserMessage(cur, eventText, eventUuid) {
  if (eventUuid && cur.some(m => m.role === 'user' && m.uuid === eventUuid)) {
    return cur
  }
  const text = eventText || ''

  if (text.includes('[添付ファイル: ')) {
    const idx = cur.findIndex(
      m => m.role === 'user' && m.optimistic && (m.fileNames?.length || m.imageUrls?.length),
    )
    if (idx >= 0) {
      const next = [...cur]
      next[idx] = { ...next[idx], uuid: eventUuid || null, optimistic: false }
      return next
    }
  }

  const exact = cur.findIndex(m => m.role === 'user' && m.optimistic && m.text === text)
  if (exact >= 0) {
    const next = [...cur]
    next[exact] = { ...next[exact], uuid: eventUuid || null, optimistic: false }
    return next
  }

  const fused = []
  cur.forEach((m, i) => {
    if (m.role === 'user' && m.optimistic && m.text && text.includes(m.text.trim())) {
      fused.push(i)
    }
  })
  if (fused.length > 0) {
    const next = [...cur]
    for (const i of fused) {
      next[i] = { ...next[i], optimistic: false }
    }
    return next
  }

  // 注: 旧版 (= 2026-06-23 早朝 5826538) は「直近 8 件に同 text non-optimistic があれば
  // append 拒否」 + 「eventUuid 無しなら append 拒否」 を追加していた。 これは fork lineage
  // 内の正当な「同 text 別 uuid」 user message が SSE replay された時に誤 drop する副作用が
  // あり、 fork タブで会話が反映されない退行を起こした。 元 bug (= ghost user message が
  // bg→fg で resurface) の root cause は「optimistic flag が立ったまま localStorage に
  // 保存される」 こと。 これは useChatStorage.js 側で load / save 両端で optimistic entry を
  // 弾くことで構造的に根治済 (= 2026-06-23)。 ここでの dedup は step [1] の uuid 一致のみで
  // 十分。 eventUuid 無しの event も append する: fork lineage 等で uuid 欠落は通常起きないが、
  // 起きた時に「画面に出ない」 より「出す」 方を採用 (= 重複した時の resurface は localStorage
  // 側で塞いだので自己強化しない)。
  return [
    ...cur,
    { id: generateId(), uuid: eventUuid || null, role: 'user', text },
  ].slice(-MAX_MESSAGES)
}
