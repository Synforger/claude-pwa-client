import { generateId } from '../../utils/id.js'
import { MAX_MESSAGES } from '../../constants.js'

// SSE 経由で受信した user_message を messages 配列に統合する純粋関数。
//
// 設計 (= 2026-06-24 server-of-truth 純化 + 2026-07-03 send_id identity 導入):
//   user message の真値は server jsonl の uuid 付き user_message のみ。 楽観 user バブル
//   (= optimistic:true) は React state にだけ存在する ephemeral 描画用、 useChatStorage 側の
//   uuid 必須 filter で永続化対象から除外される。
//
//   楽観 bubble ↔ 実 bubble 対応付けは 3 段の優先順位で決定的に走る:
//     1. eventUuid 完全一致 → 既存受信済 event の replay として no-op (dedup)
//     2. eventSendId 一致 → 楽観 bubble に焼かれた client 発行 send_id (= Idempotency-Key)
//        で厳密 pop。 backend が JSONL uuid とマッピングして event に載せる identity 経路
//     3. 近傍最後の optimistic bubble を pop (= fallback、 backend restart / TTL 超え /
//        対応付け失敗時の safety net。 単独では近似だが第 1・第 2 で拾えない時の最終手段)
//
//   4. どれも該当しなければ単純 append (= replay / proactive / fork lineage 復元)
//
// これにより「optimistic flag 取り違えで uuid なし bubble が persist → 復帰時に同 text
// 別 uuid event が来て重複 append」 の構造的 resurface 経路を根絶する (= 2026-06-23〜06-24
// 連発した重複表示バグの根治)。 加えて 2026-07-03 の 3 連発火症状は send_id 経路で
// backend dedup + updater 冪等化 + 厳密 pop の 3 段で根絶される。
export function reconcileUserMessage(cur, eventText, eventUuid, eventSendId) {
  // 1. uuid 完全一致 → 受信済の replay。 no-op。
  if (eventUuid && cur.some(m => m.role === 'user' && m.uuid === eventUuid)) {
    return cur
  }
  const text = eventText || ''

  // 2. send_id 一致で楽観 bubble を厳密 pop (identity 経路)。
  if (eventSendId) {
    const idx = cur.findIndex(
      m => m && m.role === 'user' && m.optimistic && m.send_id === eventSendId,
    )
    if (idx >= 0) return _confirmAt(cur, idx, text, eventUuid)
  }

  // 3. 近傍最後の optimistic を pop (fallback、 backend restart / TTL 超えの safety net)。
  let popIdx = -1
  for (let i = cur.length - 1; i >= 0; i--) {
    const m = cur[i]
    if (m && m.role === 'user' && m.optimistic) {
      popIdx = i
      break
    }
  }
  if (popIdx >= 0) return _confirmAt(cur, popIdx, text, eventUuid)

  // 4. 新規 append (replay / proactive / fork lineage 復元)。
  return [
    ...cur,
    { id: generateId(), uuid: eventUuid || null, role: 'user', text },
  ].slice(-MAX_MESSAGES)
}

// 楽観 bubble を実 bubble に置換する。 添付ありは元 text を保持する
// (= eventText の `[添付ファイル: ...]` を UI に出さない、 MessageItem は別経路で
// imageUrls / fileNames を render する設計)。 id は popped から継承 (= HTTP fail 経路で
// 同 bubble を狙い撃てる設計と整合)。
function _confirmAt(cur, popIdx, text, eventUuid) {
  const popped = cur[popIdx]
  const hasAttach = (popped.fileNames?.length || popped.imageUrls?.length || popped.imageRefs?.length)
  const confirmed = {
    id: popped.id,
    uuid: eventUuid || null,
    role: 'user',
    text: hasAttach ? popped.text : text,
    ...(popped.imageUrls ? { imageUrls: popped.imageUrls } : {}),
    ...(popped.imageRefs ? { imageRefs: popped.imageRefs } : {}),
    ...(popped.fileNames ? { fileNames: popped.fileNames } : {}),
  }
  const next = [...cur]
  next.splice(popIdx, 1, confirmed)
  return next
}
