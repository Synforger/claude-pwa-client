// メッセージ永続化の JSON 化 + lz-string 圧縮を main thread の外で行う worker。
//
// なぜ: 保存 1 回 = 「その sid の全 message を JSON.stringify → compressToUTF16」で、
// 長文 message が積もった session では実測 ~70ms (M2 node) / iPhone Safari 換算 150-300ms
// の main thread ブロックになる。 250ms debounce の保存が streaming の切れ目ごとに発火
// すると、 turn 中の打鍵・タップがブロック窓に落ちて無反応になる (= 2026-07-06 実害)。
// 圧縮を worker に逃がすと main thread に残るのは structured clone (数 ms) と
// localStorage.setItem (圧縮後 ~17KB、 高速) だけになる。
//
// 契約: {sid, seq, messages[]} を受けて {sid, seq, compressed} を返す。 seq は caller
// (useChatStorage) が発行する単調増加値で、 古い応答の破棄 (= 後勝ち) に使う。
import LZString from 'lz-string'

self.onmessage = (e) => {
  const { sid, seq, messages } = e.data || {}
  if (!sid || !Array.isArray(messages)) return
  const compressed = LZString.compressToUTF16(JSON.stringify(messages))
  self.postMessage({ sid, seq, compressed })
}
