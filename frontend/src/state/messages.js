// 真値 message store (= state-trace.md § 5)。 uuid 付き user / agent / system message のみ保持、
// optimistic な未確定 message は state/ephemeral.js に分離。 永続化対象 (= state/persistence.js).

import { createStore } from './_store.js'
import { isPersistableMessage } from '../domain/Message.ts'

const MAX_MESSAGES_PER_SID = 200  // v1 constants.MAX_MESSAGES と一致、 F-08

/** state shape: { [sid]: Message[] } */
const store = createStore({}, { name: 'messages' })

export const getSnapshot = () => store.getSnapshot()
export const subscribe = (listener) => store.subscribe(listener)

/** sid の message list を取得。 未存在は空配列を返す (= 参照同一性は保証されない、 hooks 側で memo)。 */
export function getMessagesFor(sid) {
  return store.getSnapshot()[sid] || []
}

/** message 1 件を末尾追加。 isPersistableMessage を満たさないものは reject (= ephemeral 側で扱う)。
 *  同 (sid, uuid) 既存があれば no-op (= reconnect replay 安全、 ADR-006 server-of-truth)。 */
export function appendMessage(sid, message) {
  if (!isPersistableMessage(message)) return
  store.setState(prev => {
    const arr = prev[sid] || []
    if (message.uuid && arr.some(m => m.uuid === message.uuid && m.role === message.role)) return prev
    let next
    if (arr.length >= MAX_MESSAGES_PER_SID) {
      next = arr.slice(arr.length - MAX_MESSAGES_PER_SID + 1)
      next.push(message)
    } else {
      next = [...arr, message]
    }
    return { ...prev, [sid]: next }
  })
}

/** sid の message list 全体を置き換え (= localStorage 復元 / fork 経路)。 */
export function setMessagesFor(sid, messages) {
  store.setState(prev => ({ ...prev, [sid]: messages.filter(isPersistableMessage) }))
}

/** 既存 message の部分更新 (= turn_duration / result event の meta 反映等、 uuid で同定)。 */
export function updateMessage(sid, uuid, patch) {
  store.setState(prev => {
    const arr = prev[sid] || []
    const idx = arr.findIndex(m => m.uuid === uuid)
    if (idx < 0) return prev
    const next = arr.slice()
    next[idx] = { ...arr[idx], ...patch }
    return { ...prev, [sid]: next }
  })
}

/** sid 削除 (= session 削除に追従)。 */
export function removeMessagesFor(sid) {
  store.setState(prev => {
    if (!(sid in prev)) return prev
    const next = { ...prev }
    delete next[sid]
    return next
  })
}

/** 初期 hydrate (= localStorage 復元): 全体差し替え。 */
export function hydrate(snapshot) {
  if (!snapshot || typeof snapshot !== 'object') return
  const filtered = {}
  for (const [sid, arr] of Object.entries(snapshot)) {
    if (Array.isArray(arr)) filtered[sid] = arr.filter(isPersistableMessage)
  }
  store.setState(filtered)
}
