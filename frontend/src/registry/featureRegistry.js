// 機能 (= feature) の有効/無効フラグ + 依存解決の registry。
// features/<name>/index.js が feature 名で register し、 layout/ が「この feature 有効か?」 で分岐。
// 例: push を無効化したら usePushSubscription も disable、 screenshare は moonlight 検出時のみ有効。

import { createRegistry } from './_registry.js'

const reg = createRegistry({
  name: 'feature',
  extractKey: (arg) => typeof arg === 'string' ? arg : (arg && typeof arg === 'object' ? arg.name : null),
  onMissing: 'silent',
})

const enabled = new Map()     // feature name -> boolean
const deps = new Map()        // feature name -> string[] (= 依存する他 feature 名)

/** Entry shape: { dispatch: (action) => any, init?, mount?, unmount?, requires?: string[] } */
export function register(name, entry, opts) {
  reg.register(name, entry, opts)
  enabled.set(name, true)  // 既定 enabled
  if (entry.requires && Array.isArray(entry.requires)) deps.set(name, entry.requires)
}

export function unregister(name) {
  reg.unregister(name)
  enabled.delete(name)
  deps.delete(name)
}

export function isEnabled(name) {
  if (!enabled.has(name)) return false
  if (!enabled.get(name)) return false
  // 依存 feature が disable されてたら本 feature も実効 disable
  const requires = deps.get(name) || []
  return requires.every(dep => isEnabled(dep))
}

export function setEnabled(name, value) {
  if (!enabled.has(name)) return
  enabled.set(name, !!value)
}

export const dispatch = (action) => reg.dispatch(action)
export const list = () => reg.list()
export const describe = (name) => reg.describe(name)
export const mountAll = () => reg.mountAll()
export const unmountAll = () => reg.unmountAll()

/** observability 用: feature 別 enabled 状態 snapshot。 */
export function getEnabledSnapshot() {
  const out = {}
  for (const name of reg.list()) out[name] = isEnabled(name)
  return out
}
