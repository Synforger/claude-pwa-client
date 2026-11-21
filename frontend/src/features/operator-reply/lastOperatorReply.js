// 会話の並びから、 操作者 に返した最後の答えを選ぶ純関数。
//
// 会話は「user の行」 を境にターンへ割れる。 操作者 の発話か、 自動の入れ替えの起動 (= phase="start"。
// 操作者 向けの報告) で始まったターンの、 最後の agent の文 (= 字のある物) が答え。 別のタブからの伝言・
// client の知らせ・入れ替えの締め・階層のタブの最初の発話で始まったターンは、 操作者 向けではないので
// 数えない (= その返事は答えにならない)。 見分けは chat/agentMessage.js の読み取りだけを使う。
// 答えの無いターンは飛ばし、 その前の 操作者 のターンの答えを残す。
// 最後の答えが入れ替えの起動のターンの物の時は、 入れ替えの前の 操作者 の発話のターンの答えも `before` で返す
// (= 新しい会話に前の答えを書き直させずに、 引き出しが両方を持つ)。

import { sortByTs } from '../chat/sortByTs.js'
import { isClientMessage, parseRollover } from '../chat/agentMessage.js'

/** 操作者 向けのターンを始める user の行か (= 操作者 の発話、 自動の入れ替えの起動)。 */
export function startsOperatorTurn(message) {
  if (message?.role !== 'user') return false
  const rollover = parseRollover(message.text)
  if (rollover) return rollover.phase === 'start'
  return !isClientMessage(message.text)
}

const hasText = (message) => typeof message.text === 'string' && message.text.trim() !== ''

/** 答えの吹き出しを区別する印 (= 同じ文が伸びても変わらず、 次の文で変わる)。 */
export const replyKeyOf = (reply) => reply?.id ?? reply?.uuid ?? null

/**
 * @param {Array<object>|null|undefined} messages  state/messages.js の 1 タブ分
 * @returns {{ prompt: object, reply: object, ongoing: boolean, before: { prompt: object, reply: object } | null } | null}
 *   prompt = ターンを始めた user の行、 reply = そのターンの最後の agent の文、
 *   ongoing = そのターンがまだ続いている (= 最後の文を agent が書いている途中)、
 *   before = 最後の答えが入れ替えの起動のターンの物の時、 その前の 操作者 の発話のターンの答え (= 無ければ null)
 */
export function lastOperatorReply(messages) {
  const ordered = sortByTs(messages || [])
  let turn = null   // 今のターンが 操作者 向けなら { prompt, reply }、 そうでなければ null
  let answered = null   // 答えのある、 いちばん新しい 操作者 向けのターン
  let spoken = null     // 答えのある、 いちばん新しい 操作者 の発話のターン (= 入れ替えの起動を除く)
  let lastBody = null   // 最後の user / agent の行 (= system の行は数えない)
  for (const message of ordered) {
    if (message.role === 'user') {
      turn = startsOperatorTurn(message) ? { prompt: message, reply: null } : null
    } else if (message.role === 'agent' && turn && hasText(message)) {
      turn.reply = message
      answered = turn
      if (!parseRollover(turn.prompt.text)) spoken = turn
    }
    if (message.role === 'user' || message.role === 'agent') lastBody = message
  }
  if (!answered) return null
  const ongoing = answered === turn && lastBody?.role === 'agent' && !!lastBody.streaming
  const before = spoken && spoken !== answered ? { prompt: spoken.prompt, reply: spoken.reply } : null
  return { prompt: answered.prompt, reply: answered.reply, ongoing, before }
}
