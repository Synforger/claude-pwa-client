// message kind (= system subtype: compact / api_error / hook_error / system_note / attachment /
// task / 等) → fromEvent + Render component の dispatch (= v1 messageRegistry.js 流儀)。
// features/chat の SystemMessages が describe(kind) で Entry を引いて render する。

import { createRegistry } from './_registry.js'

const reg = createRegistry({
  name: 'message',
  extractKey: (arg) => (arg && typeof arg === 'object') ? arg.kind : null,
  onMissing: 'silent',  // 未知 kind は features 側で plain text fallback、 ここでは silent
})

/** Entry shape: { fromEvent: (event) => props, Render: (props) => JSX } */
export const register = (kind, entry, opts) => reg.register(kind, entry, opts)
export const unregister = (kind) => reg.unregister(kind)
export const getEntry = (kind) => reg.describe(kind)
export const list = () => reg.list()

/** features/chat 側で『kind を持つ msg』 を render する経路。 dispatch は呼ばないが API 整合性のため残す。 */
export const dispatch = (msg) => reg.dispatch(msg)

export const mountAll = () => reg.mountAll()
export const unmountAll = () => reg.unmountAll()
