// 描画専用 ephemeral state (= state-trace.md § 5)。 optimistic / sendFailed / sendTimers /
// streamBuffer / attachments / loading / pendingQuestion / sendFailedText / stopUnavailableSid /
// reconnectKey を 1 store に集約。 localStorage 永続化しない (= state/persistence.js は触らない)。
//
// loading は backend SSE 由来の真値、 ephemeral 側に置くのは「optimistic で 1 瞬上書きする層」 として。

import { createStore } from './_store.js'

/** state shape: 各 field は sid 別 dict もしくは singleton。 */
const INITIAL = {
  optimistic: {},        // { [sid]: { want: 'busy'|'idle', startedAt: number } }
  sendTimers: {},        // { [sid]: timer_id }
  attachments: {},       // { [sid]: AttachmentItem[] }
  loading: {},           // { [sid]: boolean } backend authority
  apiKeySource: {},      // { [sid]: string } (system/init event)
  streamBuffers: {},     // { [sid]: { text, thinking, newTools, uuid, dirty, needsNewBubble } }
  pendingQuestion: null, // { tool_use_id, questions } or null
  sendFailedText: null,
  stopUnavailableSid: null,
  reconnectKey: 0,
}

const store = createStore(INITIAL, { name: 'ephemeral' })

export const getSnapshot = () => store.getSnapshot()
export const subscribe = (listener) => store.subscribe(listener)

// 細粒度 setter (= field 単位、 部分更新のみ subscriber 通知)

export function setOptimistic(sid, value) {
  store.setState(prev => ({ ...prev, optimistic: { ...prev.optimistic, [sid]: value } }))
}
export function clearOptimistic(sid) {
  store.setState(prev => {
    if (!(sid in prev.optimistic)) return prev
    const next = { ...prev.optimistic }; delete next[sid]
    return { ...prev, optimistic: next }
  })
}

export function setSendTimer(sid, timerId) {
  store.setState(prev => ({ ...prev, sendTimers: { ...prev.sendTimers, [sid]: timerId } }))
}
export function clearSendTimer(sid) {
  store.setState(prev => {
    if (!(sid in prev.sendTimers)) return prev
    const next = { ...prev.sendTimers }; delete next[sid]
    return { ...prev, sendTimers: next }
  })
}

export function setAttachments(sid, items) {
  store.setState(prev => ({ ...prev, attachments: { ...prev.attachments, [sid]: items } }))
}
export function clearAttachments(sid) {
  store.setState(prev => {
    if (!(sid in prev.attachments)) return prev
    const next = { ...prev.attachments }; delete next[sid]
    return { ...prev, attachments: next }
  })
}

export function setLoading(sid, isLoading) {
  store.setState(prev => {
    if (prev.loading[sid] === isLoading) return prev
    return { ...prev, loading: { ...prev.loading, [sid]: isLoading } }
  })
}

export function setApiKeySource(sid, source) {
  store.setState(prev => ({ ...prev, apiKeySource: { ...prev.apiKeySource, [sid]: source } }))
}

/** stream buffer は mutate-in-place で書く設計 (= rAF coalesce、 v1 useStreamBuffer 流儀)。
 *  ただし mutate 後に subscriber 通知が必要なので bump で reference を更新する。 */
export function getStreamBuffer(sid) {
  const buffers = store.getSnapshot().streamBuffers
  if (!buffers[sid]) {
    store.setState(prev => ({
      ...prev,
      streamBuffers: {
        ...prev.streamBuffers,
        [sid]: { text: '', thinking: null, newTools: [], uuid: null, dirty: false, needsNewBubble: false },
      },
    }))
  }
  return store.getSnapshot().streamBuffers[sid]
}

export function bumpStreamBuffer(sid) {
  // mutate-in-place した結果を listener に通知するため、 sid 単位で reference を再生成。
  store.setState(prev => ({
    ...prev,
    streamBuffers: { ...prev.streamBuffers, [sid]: { ...prev.streamBuffers[sid] } },
  }))
}

export function resetStreamBuffer(sid) {
  store.setState(prev => {
    const next = { ...prev.streamBuffers }
    next[sid] = { text: '', thinking: null, newTools: [], uuid: null, dirty: false, needsNewBubble: false }
    return { ...prev, streamBuffers: next }
  })
}

export function setPendingQuestion(q) {
  store.setState(prev => prev.pendingQuestion === q ? prev : { ...prev, pendingQuestion: q })
}

export function setSendFailedText(text) {
  store.setState(prev => prev.sendFailedText === text ? prev : { ...prev, sendFailedText: text })
}

export function setStopUnavailableSid(sid) {
  store.setState(prev => prev.stopUnavailableSid === sid ? prev : { ...prev, stopUnavailableSid: sid })
}

export function bumpReconnectKey() {
  store.setState(prev => ({ ...prev, reconnectKey: prev.reconnectKey + 1 }))
}
