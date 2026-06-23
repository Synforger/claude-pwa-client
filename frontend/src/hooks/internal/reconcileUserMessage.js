import { generateId } from '../../utils/id.js'
import { MAX_MESSAGES } from '../../constants.js'

// SSE 経由で受信した user_message を messages 配列に統合する純粋関数。
//
// 設計 (= 2026-06-24 server-of-truth 純化): user message の真値は server jsonl の
// uuid 付き user_message のみとする。 楽観 user バブル (= optimistic:true) は React state
// にだけ存在する ephemeral 描画用、 useChatStorage 側の uuid 必須 filter で永続化対象から
// 除外される。 dedup は uuid 一致のみで判定し、 旧来の text 完全一致 / 部分一致 / LOOKBACK
// 等のヒューリスティクスは全廃する。 これにより「optimistic flag を取り違えて uuid なし
// bubble が persist → 復帰時に同 text 別 uuid event が来て重複 append」 という構造的
// resurface 経路を根絶する (= 2026-06-23 〜 06-24 連発した重複表示バグの根治)。
//
// 処理:
//   1. eventUuid が既存 user message にあれば no-op (= replay の重複受信、 唯一の dedup)
//   2. 末尾近傍の最初の optimistic user bubble があれば 1 個 pop して event を append。
//      添付付き optimistic は元 text を保持する (= eventText の `[添付ファイル: ...]` を
//      UI に出さない、 MessageItem は別経路で imageUrls/fileNames を render する設計)。
//   3. optimistic が無ければ単純 append (= replay / proactive / fork lineage 復元)。
export function reconcileUserMessage(cur, eventText, eventUuid) {
  if (eventUuid && cur.some(m => m.role === 'user' && m.uuid === eventUuid)) {
    return cur
  }
  const text = eventText || ''

  let popIdx = -1
  for (let i = cur.length - 1; i >= 0; i--) {
    const m = cur[i]
    if (m && m.role === 'user' && m.optimistic) {
      popIdx = i
      break
    }
  }

  if (popIdx >= 0) {
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

  return [
    ...cur,
    { id: generateId(), uuid: eventUuid || null, role: 'user', text },
  ].slice(-MAX_MESSAGES)
}
