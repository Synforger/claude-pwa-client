// SSE event type ごとに handler を呼ぶ registry。 features/chat / status-bar / tasks 等が
// event type を register し、 transport/sse.ts が subscribe して dispatch する。

import { createRegistry } from './_registry.js'
import { isKnownEventType } from '../domain/Event.ts'

const reg = createRegistry({
  name: 'stream',
  extractKey: (event) => (event && typeof event === 'object') ? event.type : null,
  onMissing: 'warn',  // ADR-011 unknown event は graceful handle (= log warn + skip、 throw 禁止)
})

export const register = (eventType, handler, opts) => reg.register(eventType, handler, opts)
export const unregister = (eventType) => reg.unregister(eventType)
export const dispatch = (event) => {
  // 未定義 event type は ADR-011 で graceful handle (= throw 禁止、 skip + warn)
  if (event && typeof event === 'object' && !isKnownEventType(event.type)) {
    console.warn('[stream] unknown event type, skipping', event.type)
    return null
  }
  return reg.dispatch(event)
}
export const list = () => reg.list()
export const describe = (eventType) => reg.describe(eventType)
export const mountAll = () => reg.mountAll()
export const unmountAll = () => reg.unmountAll()
