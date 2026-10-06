// 別のタブの claude から届いた連絡を見分ける。
//
// backend の `POST /agent-messages` は、 本文に「誰から」 の封筒を付けて宛先のタブへ打つ。 宛先の
// 記録では人が打った発話と同じ行になるので、 見分けられるのは本文の形だけ。 1 行目 (= OPENING) は
// backend の `routes/agent_messages.py` と同じ文字列で、 backend の test が両者の一致を見ている。
// 別の機械のタブから届いた連絡は 1 行目が別の文 (= REMOTE_OPENING) で、 封筒の形は同じ。

export const AGENT_MESSAGE_OPENING =
  'Message from another session, relayed by the client (the operator did not type this):'
export const AGENT_MESSAGE_REMOTE_OPENING =
  'Message from a session on another machine, relayed by the client (the operator did not type this):'
const OPENINGS = [AGENT_MESSAGE_OPENING, AGENT_MESSAGE_REMOTE_OPENING]

// 送り主のタブで人が最後に打った発話。 backend が封筒の先頭に入れる (= 在る時だけ)。
const OPERATOR_SAID = /^<operator-said>\n([\s\S]*?)\n<\/operator-said>\n?/
// backend は中身の側の「封筒のタグと同じ形」 を &lt; に替えて届ける。 表示では元に戻す。
const restore = (text) => text.replace(/&lt;(\/?)(agent-message|operator-said)/g, '<$1$2')

const ENVELOPE = /^<agent-message from="([^"\n]*)" session="([^"\n]*)">\n([\s\S]*)\n<\/agent-message>\s*$/

/** 封筒の付いた発話なら { from, session, text, operatorSaid, remote } (= 送り主のタブ名 / タブ id /
 *  本文 / 送り主のタブで人が打った発話、 無ければ null / 別の機械から届いたか)、 違えば null。 */
export function parseAgentMessage(text) {
  if (typeof text !== 'string') return null
  // 端末への貼り付けを claude が包んで記録した分は、 backend が外してから渡す (= jsonl/events.py)。
  const trimmed = text.trimStart()
  const opening = OPENINGS.find((line) => trimmed.startsWith(line))
  if (!opening) return null
  const m = ENVELOPE.exec(trimmed.slice(opening.length).trimStart())
  if (!m) return null
  const remote = opening === AGENT_MESSAGE_REMOTE_OPENING
  // 人の発話は機械を跨がない。 別の機械からの封筒に同じ形の物が在っても、 本文として出す。
  const said = remote ? null : OPERATOR_SAID.exec(m[3])
  const body = said ? m[3].slice(said[0].length) : m[3]
  return { from: m[1], session: m[2], text: restore(body), operatorSaid: said ? restore(said[1]) : null, remote }
}
