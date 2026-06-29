// Web Push 購読状態の singleton store (= 2026-06-29 Phase J-2、 ADR-026 末尾「将来 task」 2 件目)。
//
// 旧実装は usePushSubscription 内に useState 4 個 (= hasRealSub / pushBusy / localFlag /
// pushAvailable 派生) を持っていた。 AppEffects.jsx (= mount 1 経路) と SessionDrawer.jsx
// (= drawer 開閉で remount) の 2 経路で hook が並走するため、 state が独立した instance に
// 分裂し、 visibility / interval / SW broken listener が全 instance で重複発火していた
// (= backend POST 自体は module-level の enableInflight guard で 1 本化済だが、
// 観測者の数だけ side-effect が起きる構造 = ADR-010 中央非依存 / state store backed
// 原則に反する状態だった)。
//
// 本 store で state を singleton 化 + listener を AppEffects 1 instance に集約することで、
// W2 設計本旨に揃える。 module-level `enableInflight` guard は併存 (= backend POST 重複抑止
// の最後の保険として残置)。
//
// shape:
//   available: 環境制約 (= iOS 16.4+ かつ standalone 等) で push が使えるか (= 環境固定)
//   enabled:   実 SW subscription が存在 + localStorage 希望フラグ ON (= UI 上「ON」 表示の真値)
//   broken:    希望フラグ ON だが実 subscription 無し (= 失効状態、 UI で再有効化を促す)
//   busy:      トグル中 (連打防止)

import { createStore } from './_store.js'

const INITIAL = {
  available: false,
  enabled: false,
  broken: false,
  busy: false,
}

const store = createStore(INITIAL, { name: 'push' })

export const getSnapshot = () => store.getSnapshot()
export const subscribe = (listener) => store.subscribe(listener)

export function setPushState(patch) {
  store.setState(prev => ({ ...prev, ...patch }))
}
export function setPushAvailable(value) {
  store.setState(prev => prev.available === value ? prev : { ...prev, available: value })
}
export function setPushEnabled(value) {
  store.setState(prev => prev.enabled === value ? prev : { ...prev, enabled: value })
}
export function setPushBroken(value) {
  store.setState(prev => prev.broken === value ? prev : { ...prev, broken: value })
}
export function setPushBusy(value) {
  store.setState(prev => prev.busy === value ? prev : { ...prev, busy: value })
}

// test 用: store を INITIAL に戻す (= module singleton なので各 test の beforeEach で呼ぶ)。
export function _resetForTest() {
  store.setState(() => INITIAL)
}
