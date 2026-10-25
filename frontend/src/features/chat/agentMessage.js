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
const restore = (text) => text.replace(/&lt;(\/?)(agent-message|operator-said|session-rollover)/g, '<$1$2')

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

// 自動の入れ替え (= 会話を締めて、 同じタブで新しい会話を起動し直す) で backend が打つ発話。 締めを頼む発話
// (= phase="close") と、 起動し直した会話の最初の発話 (= phase="start") が在る。 1 行目は backend の
// `core/jsonl_predicates.py` と同じ文字列で、 backend の test が両者の一致を見ている。
export const ROLLOVER_OPENING =
  'Automatic session rollover, sent by the client (the operator did not type this):'

const ROLLOVER = /^<session-rollover phase="(close|start)"((?: [a-z_]+="[^"\n]*")*)>\n([\s\S]*)\n<\/session-rollover>\s*$/

const attribute = (attributes, name) => {
  const m = new RegExp(` ${name}="([^"\n]*)"`).exec(attributes)
  return m ? m[1] : null
}

/** 自動の入れ替えの発話なら { phase, reason, contextPct, idleMinutes, text } (= 締めか起動か / 締めを頼んだ
 *  理由 `context` か `idle` / その時の context の割合 / 静かだった分数 / 本文)、 違えば null。
 *  起動の発話は reason と数字を持たない (= null)。 */
export function parseRollover(text) {
  if (typeof text !== 'string') return null
  const trimmed = text.trimStart()
  if (!trimmed.startsWith(ROLLOVER_OPENING)) return null
  const m = ROLLOVER.exec(trimmed.slice(ROLLOVER_OPENING.length).trimStart())
  if (!m) return null
  const number = (name) => {
    const value = attribute(m[2], name)
    return value !== null && /^\d+$/.test(value) ? Number(value) : null
  }
  return {
    phase: m[1],
    reason: attribute(m[2], 'reason'),
    contextPct: number('context_pct'),
    idleMinutes: number('idle_minutes'),
    text: restore(m[3]),
  }
}

// backend がエージェントの階層ごとに立てたタブの、 最初の発話。 1 行目は backend の
// `jsonl/jsonl_predicates.py` と同じ文字列で、 backend の test が両者の一致を見ている。
export const TAB_OPEN_OPENING =
  'Tab opened by the client for its tier (the operator did not type this):'

const TAB_OPEN = /^<tab-open>\n([\s\S]*?)\n<\/tab-open>\s*$/

/** 階層のタブの最初の発話なら { tier } (= 立てた階層。 `tier=` の行が無ければ null)、 違えば null。 */
export function parseTabOpen(text) {
  if (typeof text !== 'string') return null
  const trimmed = text.trimStart()
  if (!trimmed.startsWith(TAB_OPEN_OPENING)) return null
  const m = TAB_OPEN.exec(trimmed.slice(TAB_OPEN_OPENING.length).trimStart())
  if (!m) return null
  const line = m[1].split('\n').find((l) => l.startsWith('tier='))
  return { tier: line ? line.slice('tier='.length).trim() : null }
}

/** 端末から入ったが人が打っていない発話か (= 別のタブからの連絡、 自動の入れ替えの発話、 階層のタブの最初の発話)。 */
export const isClientMessage = (text) => !!(parseAgentMessage(text) || parseRollover(text) || parseTabOpen(text))
