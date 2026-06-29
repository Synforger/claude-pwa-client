// 描画専用 ephemeral state (= state-trace.md § 5)。 streamBuffer / attachments / loading /
// apiKeySource / sendFailedText / stopUnavailableSid / reconnectKey を 1 store に集約。
// localStorage 永続化しない (= state/persistence.js は触らない)。
//
// loading は backend SSE 由来の真値、 ephemeral 側に置くのは「optimistic で 1 瞬上書きする層」 として。
//
// Phase J-12 (= 2026-06-29、 audit-w2-residue B 14 件 sweep): optimistic / sendTimers /
// pendingQuestion を retire (= 真値は useChatStream 内 useRef / useStatus の SSE)。 audit B の
// orphan setter を削減、 store 設計を実 consumer に揃える。

import { createStore } from './_store.js'

/** state shape: 各 field は sid 別 dict もしくは singleton。 */
const INITIAL = {
  attachments: {},       // { [sid]: AttachmentItem[] }
  loading: {},           // { [sid]: boolean } backend authority
  apiKeySource: {},      // { [sid]: string } (system/init event)
  streamBuffers: {},     // { [sid]: { text, thinking, newTools, uuid, dirty, needsNewBubble } }
  sendFailedText: null,  // string | null (= F-36 ChatInput.localText 復元用、 active sid 限定で write)
  stopUnavailableSid: null, // string | null (= F-16 stop が WS 切断中、 ChatInput tooltip 用)
  reconnectKey: 0,
}

const store = createStore(INITIAL, { name: 'ephemeral' })

export const getSnapshot = () => store.getSnapshot()
export const subscribe = (listener) => store.subscribe(listener)

// 細粒度 setter (= field 単位、 部分更新のみ subscriber 通知)

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

/** Phase J-9 (= 2026-06-29): backend 再起動検知時等の全クリア (= useChatStream の旧 setLoading({}) 経路)。 */
export function clearLoading() {
  store.setState(prev => {
    if (Object.keys(prev.loading).length === 0) return prev
    return { ...prev, loading: {} }
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

/** ChatInput が送信失敗 text を localText に復元するための通知 (= F-36)。
 *  value = text string or null。 active sid に対する書き込みのみ意味を持つ (= caller が gating)。
 *  ChatInput が consume したら null に戻す (= one-shot)。 */
export function setSendFailedText(value) {
  store.setState(prev => prev.sendFailedText === value ? prev : { ...prev, sendFailedText: value })
}

/** WS 切断中に押された stopMessage の通知 (= F-16)。 ChatInput が tooltip 表示用に subscribe。
 *  value = sid string or null。 復活後に null に戻す。 */
export function setStopUnavailableSid(sid) {
  store.setState(prev => prev.stopUnavailableSid === sid ? prev : { ...prev, stopUnavailableSid: sid })
}

export function bumpReconnectKey() {
  store.setState(prev => ({ ...prev, reconnectKey: prev.reconnectKey + 1 }))
}
