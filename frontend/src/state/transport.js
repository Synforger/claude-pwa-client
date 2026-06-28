// transport-derived state (= state-trace.md § 5)。 isOnline (= 旧 useConnectionStatus 集約) +
// offsets (= transport/sse.js から昇格、 hooks 経由で読みたい場合の派生)。

import { createStore } from './_store.js'

const INITIAL = {
  isOnline: true,
  offsets: {},  // { [sid]: number }
}

const store = createStore(INITIAL, { name: 'transport' })

export const getSnapshot = () => store.getSnapshot()
export const subscribe = (listener) => store.subscribe(listener)

export function setOnline(isOnline) {
  store.setState(prev => prev.isOnline === isOnline ? prev : { ...prev, isOnline })
}

export function setOffset(sid, offset) {
  store.setState(prev => {
    if (prev.offsets[sid] === offset) return prev
    return { ...prev, offsets: { ...prev.offsets, [sid]: offset } }
  })
}

export function setOffsets(snapshot) {
  store.setState(prev => ({ ...prev, offsets: snapshot || {} }))
}
