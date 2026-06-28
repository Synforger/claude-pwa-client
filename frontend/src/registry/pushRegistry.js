// push channel (= subscription kind / event kind) ごとの handler dispatch。
// features/push-notify が register、 Service Worker / backend からの push event を分配する。

import { createRegistry } from './_registry.js'

const reg = createRegistry({
  name: 'push',
  extractKey: (arg) => (arg && typeof arg === 'object') ? (arg.channel || arg.kind) : null,
  onMissing: 'warn',
})

export const register = (channel, handler, opts) => reg.register(channel, handler, opts)
export const unregister = (channel) => reg.unregister(channel)
export const dispatch = (event) => reg.dispatch(event)
export const list = () => reg.list()
export const describe = (channel) => reg.describe(channel)
export const mountAll = () => reg.mountAll()
export const unmountAll = () => reg.unmountAll()
