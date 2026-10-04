// 別のタブの claude から届いた連絡を見分ける。
//
// backend の `POST /agent-messages` は、 本文に「誰から」 の封筒を付けて宛先のタブへ打つ。 宛先の
// 記録では人が打った発話と同じ行になるので、 見分けられるのは本文の形だけ。 1 行目 (= OPENING) は
// backend の `routes/agent_messages.py` と同じ文字列で、 backend の test が両者の一致を見ている。

export const AGENT_MESSAGE_OPENING =
  'Message from another session, relayed by the client (the operator did not type this):'

const ENVELOPE = /^<agent-message from="([^"\n]*)" session="([^"\n]*)">\n([\s\S]*)\n<\/agent-message>\s*$/

/** 封筒の付いた発話なら { from, session, text } (= 送り主のタブ名 / タブ id / 本文)、 違えば null。 */
export function parseAgentMessage(text) {
  if (typeof text !== 'string') return null
  const trimmed = text.trimStart()
  if (!trimmed.startsWith(AGENT_MESSAGE_OPENING)) return null
  const m = ENVELOPE.exec(trimmed.slice(AGENT_MESSAGE_OPENING.length).trimStart())
  if (!m) return null
  return { from: m[1], session: m[2], text: m[3].replaceAll('&lt;/agent-message', '</agent-message') }
}
