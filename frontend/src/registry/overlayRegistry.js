// overlay (= modal / drawer / panel) の open/close 統一 dispatch。
// features/session-drawer 等が overlay 種別を register し、 layout/ から open(name, payload) /
// close(name) を呼ぶ。 ui state の overlay flag (= state/ui.js) も同時に揺らす。

import { createRegistry } from './_registry.js'
import { setOverlay } from '../state/ui.js'

const reg = createRegistry({
  name: 'overlay',
  extractKey: (arg) => (arg && typeof arg === 'object') ? arg.name : null,
  onMissing: 'warn',
})

/** Entry shape: { dispatch: (action) => any, Component?, init?, mount?, unmount? }
 *  action = { type: 'open' | 'close', name, payload? }
 *
 *  Component (= optional): `() => Promise<{ default: ReactComponent }>` 形式の lazy spec
 *  (= W2 Phase E1)。 OverlayHost が registry を走査して describe(name).Component を React.lazy
 *  に渡し、 ui.overlays[name] が truthy になった瞬間に Suspense + LazyBoundary で render する。
 *  全 entry が Component spec 登録済み (= E-2 完了)。 spec を持たない entry は render されない。
 *  _registry.js は handler shape を最小チェック (= dispatch 関数だけ必須) で受けるので、
 *  Component は handler entry にそのまま保持され describe(name).Component で取り出せる。 */
export const register = (name, handler, opts) => reg.register(name, handler, opts)
export const unregister = (name) => reg.unregister(name)
export const describe = (name) => reg.describe(name)
export const list = () => reg.list()

export function open(name, payload) {
  setOverlay(name, payload ?? true)
  return reg.dispatch({ type: 'open', name, payload })
}

export function close(name) {
  setOverlay(name, false)
  return reg.dispatch({ type: 'close', name })
}

export const mountAll = () => reg.mountAll()
export const unmountAll = () => reg.unmountAll()
