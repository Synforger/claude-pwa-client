// A sent bubble that did not reach Claude: marked `sendFailed` (= MessageItem shows the note under it), and the empty
// "thinking" bubbles behind it are dropped, since no answer is coming. Called by the send itself when its HTTP answer
// fails, and by the stream when the backend says a message it held was not taken (`send_failed`).

// The messages with the first user bubble that `match` picks marked as not delivered. → `{ next, text }`, or null when
// no such bubble waits for its confirmation (= it was confirmed already, or marked before).
export function failUserBubble(messages, match) {
  const index = messages.findIndex(m => m && m.role === 'user' && match(m))
  if (index < 0) return null
  const target = messages[index]
  if (target.uuid || target.sendFailed) return null
  const next = [...messages]
  next[index] = { ...target, sendFailed: true }
  while (next.length) {
    const tail = next[next.length - 1]
    if (tail.role === 'agent' && tail.streaming && !tail.text && !tail.thinking && (!tail.tools || !tail.tools.length)) {
      next.pop()
    } else break
  }
  return { next, text: target.text || '' }
}
