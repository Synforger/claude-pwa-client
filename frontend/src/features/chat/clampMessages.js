// Keeps each conversation's message list at MAX_MESSAGES: the one place that bounds the lists in memory.
// useChatStorage wraps the setter it hands out with this, so every path that adds a message (a streamed assistant
// frame, a system card, a question, a sent message, a session end marker, a replay of the history) is bounded
// without each one cutting for itself.
import { MAX_MESSAGES } from '../../_common/constants.js'
import { sortByTs } from './sortByTs.js'

/**
 * `list` without its oldest messages, so that it holds `max`. "Oldest" is the order the chat draws them in
 * (sortByTs), not the position in the array: the array is in the order messages arrived, and a replay of the history
 * appends old rows at its end. The messages that stay keep their array order. The same array comes back when it
 * already holds `max` or fewer.
 */
export function dropOldestMessages(list, max = MAX_MESSAGES) {
  if (!Array.isArray(list) || list.length <= max) return list
  const dropped = new Set(sortByTs(list).slice(0, list.length - max))
  return list.filter(message => !dropped.has(message))
}

/**
 * The next `{ [sid]: messages[] }` with every conversation that changed held to `max`. A conversation whose array
 * is the one it was before is passed over without a look (so a change in one conversation costs nothing to the
 * others). The same object comes back when nothing had to be cut.
 */
export function clampMessageDict(prev, next, max = MAX_MESSAGES) {
  if (next === prev || !next || typeof next !== 'object') return next
  let clamped = null
  for (const sid of Object.keys(next)) {
    const list = next[sid]
    if (list === prev?.[sid]) continue
    const kept = dropOldestMessages(list, max)
    if (kept === list) continue
    if (!clamped) clamped = { ...next }
    clamped[sid] = kept
  }
  return clamped || next
}
