// Marks the bubble of a text the backend keeps until the window of the tab closes, and takes away the empty bubble of
// the answer that does not come yet. Pure. Used by useChatStream.js.

/**
 * @param {object[]} messages the tab's messages
 * @param {(message: object) => boolean} match picks the bubble of the kept text
 * @returns {object[] | null} the new messages; null when the bubble is not there or is already settled
 */
export function holdUserBubble(messages, match) {
  const index = messages.findIndex(m => m && m.role === 'user' && match(m))
  if (index < 0) return null
  const target = messages[index]
  if (target.uuid || target.sendFailed) return null
  const next = [...messages]
  next[index] = { ...target, heldByWindow: true }
  while (next.length) {
    const tail = next[next.length - 1]
    if (tail.role === 'agent' && tail.streaming && !tail.text && !tail.thinking && !tail.tools?.length) next.pop()
    else break
  }
  return next
}
