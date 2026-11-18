import { stripAnsi } from './format.js'

// tool_result 本文から表示に使われないデータを落とすための純関数群。
//
// backend は履歴 GET (= /jsonl/history) で同じ縮小を掛けている
// (= backend/jsonl/routes.py::_shrink_tool_results、 2026-07-27)。 一方ライブ SSE は
// 「進行中の tool 出力を完全な形で届ける」 契約なので無改変で流れてくる。 結果として
// **履歴経由の同じ会話は軽く、 ライブ経由だけ重い**という非対称が client 側に残っていた。
// ここはその対称化で、 端末が受け取った後の state / localStorage に載る形を揃える。
//
// 落とすのは tool_result 内の image ブロックの本体だけ。 UI は tool_result 内の画像を実データ
// として描画せず「画像」 プレースホルダ 1 語に畳む (= _common/format.js formatToolResultContent
// の `type === 'image'` 経路) ので、 本体は 1 byte も表示に使われない。 `type` は残すので
// プレースホルダ表示は不変。

/**
 * tool_result の content から image ブロックの本体を落とす。
 * content は string / block list の両形があり、 string はそのまま返す。
 * 落とすものが無ければ **引数と同じ参照**を返す (= 上位の参照比較 / 再 render を壊さない)。
 */
export function stripToolResultImages(content) {
  if (!Array.isArray(content)) return content
  let stripped = false
  const out = content.map(block => {
    if (!block || block.type !== 'image') return block
    // 既に本体が無い (= 履歴 GET が落とした後 / 復元済み) なら現状維持
    if (Object.keys(block).length === 1) return block
    stripped = true
    return { type: 'image' }
  })
  return stripped ? out : content
}

/**
 * message 1 件の tools[].result.content に stripToolResultImages を掛ける。
 * 落とすものが無ければ引数と同じ参照を返す。
 */
export function stripMessageToolResultImages(msg) {
  if (!msg || !Array.isArray(msg.tools) || msg.tools.length === 0) return msg
  let mutated = false
  const tools = msg.tools.map(tool => {
    const content = tool?.result?.content
    if (content == null) return tool
    const next = stripToolResultImages(content)
    if (next === content) return tool
    mutated = true
    return { ...tool, result: { ...tool.result, content: next } }
  })
  return mutated ? { ...msg, tools } : msg
}

/**
 * Cuts the text of a tool_result's content to `limit` characters, the way the backend cuts the history
 * (`_shrink_tool_results` in backend/jsonl/routes.py): a string is cut as it is; in a block list the text blocks
 * share the budget in order and every other block is kept. `plain` strips ANSI codes first (the screen strips
 * them too), so the kept text is what is drawn.
 * Returns `{ content, fullChars }`. `fullChars` is the length before the cut, and null when nothing was cut. The
 * same `content` reference comes back when nothing was cut.
 */
export function capToolResultText(content, limit, { plain = false } = {}) {
  if (typeof content === 'string') {
    const text = plain ? stripAnsi(content) : content
    if (text.length <= limit) return { content: text === content ? content : text, fullChars: null }
    return { content: text.slice(0, limit), fullChars: text.length }
  }
  if (!Array.isArray(content)) return { content, fullChars: null }
  let total = 0
  let budget = limit
  let changed = false
  const kept = content.map(block => {
    if (!block || typeof block.text !== 'string') return block
    const text = plain ? stripAnsi(block.text) : block.text
    total += text.length
    if (budget <= 0) { changed = true; return null }
    const piece = text.length > budget ? text.slice(0, budget) : text
    budget -= piece.length
    if (piece === block.text) return block
    changed = true
    return { ...block, text: piece }
  }).filter(block => block !== null)
  if (!changed) return { content, fullChars: null }
  return { content: kept, fullChars: total > limit ? total : null }
}

/**
 * Cuts the text of every tool result of a message to `limit` characters and records the length before the cut in
 * `result.full_chars` (the screen draws that number as the size of the result). A length a result already carries
 * (the backend cut it first) is kept when it is the larger. The same message reference comes back when nothing
 * changes.
 */
export function capMessageToolResults(msg, limit, options) {
  if (!msg || !Array.isArray(msg.tools) || msg.tools.length === 0) return msg
  let mutated = false
  const tools = msg.tools.map(tool => {
    const result = tool?.result
    if (!result || result.content == null) return tool
    const { content, fullChars } = capToolResultText(result.content, limit, options)
    if (content === result.content) return tool
    mutated = true
    const known = typeof result.full_chars === 'number' ? result.full_chars : 0
    const full = Math.max(known, fullChars ?? 0)
    return { ...tool, result: { ...result, content, ...(full > 0 ? { full_chars: full } : {}) } }
  })
  return mutated ? { ...msg, tools } : msg
}
