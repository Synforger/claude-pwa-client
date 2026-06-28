// 全 state/ store の共通基盤 (= ADR-017)。
// React 19 useSyncExternalStore 接続用の subscribe/getSnapshot を統一、 1 経路で observability
// (= W3 DebugPanel / StateInspector / event_journal) が「全 store の現在値を読む」 構造を作る。
//
// 使い方:
//   import { createStore } from './_store.js'
//   const store = createStore({ messages: {} })
//
//   export function getSnapshot() { return store.getSnapshot() }
//   export function subscribe(listener) { return store.subscribe(listener) }
//   export function setMessages(updater) { store.setState(s => ({ ...s, messages: typeof updater === 'function' ? updater(s.messages) : updater })) }
//
//   // React 側 (features 層):
//   const snapshot = useSyncExternalStore(subscribe, getSnapshot)

const REGISTRY = new Map()  // store name -> store (= debug inspector が全 store 走査するため)

export function createStore(initial, opts = {}) {
  const { name = `anon-${REGISTRY.size}`, equals = Object.is } = opts
  let state = initial
  const listeners = new Set()

  function getSnapshot() { return state }

  function setState(next) {
    const updated = typeof next === 'function' ? next(state) : next
    if (equals(updated, state)) return  // no-op (= snapshot reference 同一は subscriber 通知しない)
    state = updated
    // listener から再 setState されるケースに備えてコピー走査
    for (const fn of Array.from(listeners)) {
      try { fn(state) } catch (e) { console.error(`[store:${name}] listener threw`, e) }
    }
  }

  function subscribe(listener) {
    listeners.add(listener)
    return () => listeners.delete(listener)
  }

  const store = { name, getSnapshot, setState, subscribe }
  REGISTRY.set(name, store)
  return store
}

/** observability 用: 全 store の現在値を name -> snapshot で返す (= W3 inspector 入口、 副作用なし)。 */
export function getAllStoreSnapshots() {
  const out = {}
  for (const [name, store] of REGISTRY.entries()) {
    out[name] = store.getSnapshot()
  }
  return out
}

/** observability 用: 全 store に listener を貼って差分を観測する (= EventTimeline 配線用、 cleanup 返す)。 */
export function subscribeAllStores(listener) {
  const unsubs = []
  for (const [name, store] of REGISTRY.entries()) {
    unsubs.push(store.subscribe((value) => { listener(name, value) }))
  }
  return () => { for (const u of unsubs) u() }
}

/** test 用: 全 store の name 列挙。 prod では DebugPanel が叩く。 */
export function listStoreNames() {
  return Array.from(REGISTRY.keys())
}
