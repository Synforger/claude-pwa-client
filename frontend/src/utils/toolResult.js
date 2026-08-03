// tool_result 本文から表示に使われないデータを落とすための純関数群。
//
// backend は履歴 GET (= /jsonl/history) で同じ縮小を掛けている
// (= backend/jsonl/routes.py::_shrink_tool_results、 2026-07-27)。 一方ライブ SSE は
// 「進行中の tool 出力を完全な形で届ける」 契約なので無改変で流れてくる。 結果として
// **履歴経由の同じ会話は軽く、 ライブ経由だけ重い**という非対称が client 側に残っていた。
// ここはその対称化で、 端末が受け取った後の state / localStorage に載る形を揃える。
//
// 落とすのは tool_result 内の image ブロックの本体だけ。 UI は tool_result 内の画像を実データ
// として描画せず「画像」 プレースホルダ 1 語に畳む (= utils/format.js formatToolResultContent
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
