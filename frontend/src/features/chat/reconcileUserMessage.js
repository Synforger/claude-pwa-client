import { generateId } from '../../utils/id.js'
import { MAX_MESSAGES } from '../../constants.js'
import { isStaleFor } from './replayGuard.js'

// SSE 経由で受信した user_message を messages 配列に統合する純粋関数。
//
// 設計 (= 2026-06-24 server-of-truth 純化 + 2026-07-03 send_id identity 導入 +
// 2026-07-10 identity 終身保持):
//   user message の真値は server jsonl の uuid 付き user_message のみ。 楽観 user バブル
//   (= optimistic:true) は React state にだけ存在する ephemeral 描画用、 useChatStorage 側の
//   uuid 必須 filter で永続化対象から除外される。
//
//   楽観 bubble ↔ 実 bubble 対応付けは段階の優先順位で決定的に走る:
//     1. eventUuid 完全一致 → 既存受信済 event の replay として no-op (dedup)
//     2. eventSendId 一致 (= 楽観 bubble に焼かれた client 発行 send_id = Idempotency-Key)
//        a. optimistic を厳密 pop (= identity 経路の本線)
//        b. **確定済 bubble に同 send_id** → 同一送信の再配信。 append せず uuid backfill のみ
//           (= 2026-07-10 根治: 旧 _confirmAt は確定時に send_id を捨てていたため、 uuid 対応の
//           取りこぼしと再配信が重なると同じ送信が新規扱いされ、 同文バブルが 2 個出て
//           「二重送信に見える」。 send_id は確定後も一生持たせる)
//     3. 近傍最後の optimistic bubble を pop (= fallback、 backend restart / TTL 超え /
//        対応付け失敗時の safety net。 単独では近似だが第 1・第 2 で拾えない時の最終手段)
//     3.5 同文採用 guard: identity が全部切れた配信でも、 直近に uuid 未確定の同文 user bubble が
//        居ればそれを確定させる (= 新規 append しない)。 uuid 未確定の同文 = 対応付けそこねた
//        自分の送信であって新規発話ではない、 が物理。 意図的な同文連投は既存 bubble が uuid
//        確定済なのでここに落ちず、 正しく append される
//     4. どれも該当しなければ単純 append (= replay / proactive / fork lineage 復元)
//
// これにより「optimistic flag 取り違えで uuid なし bubble が persist → 復帰時に同 text
// 別 uuid event が来て重複 append」 の構造的 resurface 経路を根絶する (= 2026-06-23〜06-24
// 連発した重複表示バグの根治)。 加えて 2026-07-03 の 3 連発火症状は send_id 経路で
// backend dedup + updater 冪等化 + 厳密 pop の 3 段で根絶される。
export function reconcileUserMessage(cur, eventText, eventUuid, eventSendId, eventTs) {
  // 1. uuid 完全一致 → 受信済の replay。 no-op。
  if (eventUuid && cur.some(m => m.role === 'user' && m.uuid === eventUuid)) {
    return cur
  }
  const text = eventText || ''

  // 2. send_id 一致 (identity 経路)。
  if (eventSendId) {
    // 2a. optimistic を厳密 pop。
    const idx = cur.findIndex(
      m => m && m.role === 'user' && m.optimistic && m.send_id === eventSendId,
    )
    if (idx >= 0) return _confirmAt(cur, idx, text, eventUuid, eventSendId, eventTs)
    // 2b. 確定済 bubble の同 send_id で **uuid 未確定** = 同一送信の再配信。 append せず
    // uuid backfill のみ。 bubble が既に別 uuid を持つ場合はここで扱わない (= uuid が最終
    // 権威。 同 send_id + 別 uuid は別メッセージとして下段へ流し従来通り append される)。
    const cIdx = cur.findIndex(
      m => m && m.role === 'user' && !m.optimistic && !m.uuid && m.send_id === eventSendId,
    )
    if (cIdx >= 0) {
      const b = cur[cIdx]
      if (eventUuid) {
        const next = [...cur]
        next[cIdx] = { ...b, uuid: eventUuid }
        return next
      }
      return cur
    }
  }

  // 3. 近傍最後の optimistic を pop (fallback、 backend restart / TTL 超えの safety net)。
  // ただし **event が その optimistic より過去なら pop しない** (= 2026-07-26 根治)。
  // identity (uuid / send_id) が両方切れた event に対する近似 match なので、 GET 履歴
  // replay で流れてくる**古い** user_message もここに落ちる。 無条件に pop すると、
  // 送信直後の楽観バブルが大昔の発話で上書きされて消える (= 実機報告「自分のメッセージが
  // 消えてる」 の直接原因、 再現 test 済)。 未確定バブルを確定できるのはその送信より後に
  // 生まれた event だけ、 が物理。
  let popIdx = -1
  for (let i = cur.length - 1; i >= 0; i--) {
    const m = cur[i]
    if (m && m.role === 'user' && m.optimistic) {
      if (isStaleFor(eventTs, m.ts)) break  // 過去の event = この送信の確定ではない → append へ
      popIdx = i
      break
    }
  }
  if (popIdx >= 0) return _confirmAt(cur, popIdx, text, eventUuid, eventSendId, eventTs)

  // 3.5 同文採用 guard: 直近 8 bubble に uuid 未確定の同文 user bubble → それを確定
  // (= 見た目二重の構造的禁止。 uuid 確定済の同文は意図的連投なので対象外 = append へ)。
  if (text) {
    for (let i = cur.length - 1; i >= Math.max(0, cur.length - 8); i--) {
      const m = cur[i]
      if (m && m.role === 'user' && !m.uuid && (m.text || '') === text) {
        return _confirmAt(cur, i, text, eventUuid, eventSendId || m.send_id, eventTs)
      }
    }
  }

  // 4. 新規 append (replay / proactive / fork lineage 復元)。
  return [
    ...cur,
    {
      id: generateId(),
      uuid: eventUuid || null,
      role: 'user',
      text,
      ...(eventSendId ? { send_id: eventSendId } : {}),
      ...(eventTs != null ? { ts: eventTs } : {}),
    },
  ].slice(-MAX_MESSAGES)
}

// 楽観 bubble を実 bubble に置換する。 添付ありは元 text を保持する
// (= eventText の `[添付ファイル: ...]` を UI に出さない、 MessageItem は別経路で
// imageUrls / fileNames を render する設計)。 id は popped から継承 (= HTTP fail 経路で
// 同 bubble を狙い撃てる設計と整合)。 send_id も継承 (= 2026-07-10: 再配信を 2b で
// 同一送信と識別するための終身 identity。 捨てると再配信が新規 append され見た目二重)。
function _confirmAt(cur, popIdx, text, eventUuid, sendId, eventTs) {
  const popped = cur[popIdx]
  const hasAttach = (popped.fileNames?.length || popped.imageUrls?.length || popped.imageRefs?.length)
  const keptSendId = sendId || popped.send_id
  // ts は **必ず引き継ぐ** (= 2026-07-27 「送信した瞬間に自分のメッセージが消える」 根治)。
  // 表示は ts で時系列ソートしてから末尾 DISPLAY_LIMIT 件を採る設計 (= 中抜け根治) なので、
  // ts を失った bubble は直前要素の実効キーを継ぐ。 配列上の直前が replay 由来の**古い**
  // メッセージだと、 確定したばかりの自分の発話が過去に沈んで表示窓の外へ押し出され、
  // 送信直後に消えたように見える。 server ts を優先し、 無ければ楽観 bubble の ts を残す。
  const keptTs = typeof eventTs === 'number' ? eventTs
    : (typeof popped.ts === 'number' ? popped.ts : null)
  const confirmed = {
    id: popped.id,
    uuid: eventUuid || null,
    role: 'user',
    text: hasAttach ? popped.text : text,
    ...(keptTs != null ? { ts: keptTs } : {}),
    ...(keptSendId ? { send_id: keptSendId } : {}),
    ...(popped.imageUrls ? { imageUrls: popped.imageUrls } : {}),
    ...(popped.imageRefs ? { imageRefs: popped.imageRefs } : {}),
    ...(popped.fileNames ? { fileNames: popped.fileNames } : {}),
  }
  const next = [...cur]
  next.splice(popIdx, 1, confirmed)
  return next
}
