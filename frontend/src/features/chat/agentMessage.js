// 別のタブの claude から届いた連絡を見分ける。
//
// backend の `POST /agent-messages` は、 本文に「誰から」 の封筒を付けて宛先のタブへ打つ。 宛先の
// 記録では人が打った発話と同じ行になるので、 見分けられるのは本文の形だけ。 1 行目 (= OPENING) は
// backend の `routes/agent_messages.py` と同じ文字列で、 backend の test が両者の一致を見ている。

export const AGENT_MESSAGE_OPENING =
  'Message from another session, relayed by the client (the operator did not type this):'

// Claude Code は複数行の貼り付けを <pasted_content id="N">…</pasted_content id="N"> で包んで記録する。
// 連絡は端末への貼り付けで届くので、 実物の行はこの包みの中に封筒が入った形になる。
const PASTED = /^<pasted_content[^>\n]*>\n?([\s\S]*?)\n?<\/pasted_content[^>\n]*>$/

// 送り主のタブで人が最後に打った発話。 backend が封筒の先頭に入れる (= 在る時だけ)。
const OPERATOR_SAID = /^<operator-said>\n([\s\S]*?)\n<\/operator-said>\n?/
// backend は中身の側の「封筒のタグと同じ形」 を &lt; に替えて届ける。 表示では元に戻す。
const restore = (text) => text.replace(/&lt;(\/?)(agent-message|operator-said)/g, '<$1$2')

const ENVELOPE = /^<agent-message from="([^"\n]*)" session="([^"\n]*)">\n([\s\S]*)\n<\/agent-message>\s*$/

/** 封筒の付いた発話なら { from, session, text, operatorSaid } (= 送り主のタブ名 / タブ id / 本文 /
 *  送り主のタブで人が打った発話、 無ければ null)、 違えば null。 */
export function parseAgentMessage(text) {
  if (typeof text !== 'string') return null
  const pasted = PASTED.exec(text.trim())
  const trimmed = (pasted ? pasted[1] : text).trimStart()
  if (!trimmed.startsWith(AGENT_MESSAGE_OPENING)) return null
  const m = ENVELOPE.exec(trimmed.slice(AGENT_MESSAGE_OPENING.length).trimStart())
  if (!m) return null
  const said = OPERATOR_SAID.exec(m[3])
  const body = said ? m[3].slice(said[0].length) : m[3]
  return { from: m[1], session: m[2], text: restore(body), operatorSaid: said ? restore(said[1]) : null }
}
