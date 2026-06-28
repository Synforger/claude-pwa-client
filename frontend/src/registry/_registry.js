// 全 registry/ の共通基盤 (= ADR-010 lifecycle 契約型 + ADR-017 と対称な共通化 pattern)。
// 5 registry (= stream / message / overlay / push / feature) が同じ subscribe / register /
// dispatch を持つので、 factory に集約する。 W3 observability で「全 registry の登録状況を 1 経路で
// snapshot」 する入口にもなる。

const REGISTRY_META = new Map()  // registry name -> { extractKey fn, handlers Map }

/** RegistryHandler は ADR-010 lifecycle 契約型:
 *    interface RegistryHandler {
 *      init?: () => void | Promise<void>     // register 直後に 1 回
 *      mount?: () => void                    // App.jsx mount 後 dispatch 開始前
 *      unmount?: () => void                  // hot reload / feature disable
 *      dispatch: (arg) => any                // 必須
 *    }
 */

export function createRegistry(options) {
  const {
    name,
    extractKey,                           // (arg) => key、 dispatch 時の key 抽出関数
    onMissing = 'warn',                   // 'warn' | 'throw' | 'silent'
  } = options
  if (!name || typeof extractKey !== 'function') {
    throw new Error(`createRegistry: name + extractKey required`)
  }

  const handlers = new Map()
  REGISTRY_META.set(name, { extractKey, handlers })

  function register(key, handler, opts = {}) {
    if (!handler || typeof handler.dispatch !== 'function') {
      throw new Error(`registry[${name}]: handler.dispatch required for key=${key}`)
    }
    if (handlers.has(key) && !opts.replace) {
      // loud fail (= silent skip 蓄積の構造的根本対策、 設計書 § 2-4)
      throw new Error(`registry[${name}] conflict: ${key} (pass {replace:true} for hot reload)`)
    }
    handlers.set(key, handler)
    if (handler.init) {
      Promise.resolve(handler.init()).catch(e => console.error(`registry[${name}] init failed: ${key}`, e))
    }
  }

  function unregister(key) {
    const h = handlers.get(key)
    if (!h) return
    try { h.unmount?.() } catch (e) { console.error(`registry[${name}] unmount failed: ${key}`, e) }
    handlers.delete(key)
  }

  function dispatch(arg) {
    const key = extractKey(arg)
    if (key === null || key === undefined) {
      if (onMissing === 'throw') throw new Error(`registry[${name}]: extractKey returned null`)
      if (onMissing === 'warn') console.warn(`registry[${name}]: extractKey returned null`, arg)
      return null
    }
    const h = handlers.get(key)
    if (!h) {
      if (onMissing === 'throw') throw new Error(`registry[${name}]: no handler for ${key}`)
      if (onMissing === 'warn') console.warn(`registry[${name}]: no handler for ${key}`, arg)
      return null
    }
    try { return h.dispatch(arg) }
    catch (e) { console.error(`registry[${name}] dispatch failed: ${key}`, e); return null }
  }

  function mountAll() {
    for (const [key, h] of handlers.entries()) {
      try { h.mount?.() } catch (e) { console.error(`registry[${name}] mount failed: ${key}`, e) }
    }
  }

  function unmountAll() {
    for (const [key, h] of handlers.entries()) {
      try { h.unmount?.() } catch (e) { console.error(`registry[${name}] unmount failed: ${key}`, e) }
    }
  }

  function list() { return Array.from(handlers.keys()) }
  function describe(key) { return handlers.get(key) }
  function size() { return handlers.size }

  return { name, register, unregister, dispatch, mountAll, unmountAll, list, describe, size }
}

/** observability 用: 全 registry の登録状況 (= name -> [keys]) を返す。 W3 debug/ で叩く。 */
export function getAllRegistrySnapshots() {
  const out = {}
  for (const [name, meta] of REGISTRY_META.entries()) {
    out[name] = Array.from(meta.handlers.keys())
  }
  return out
}

/** test 用: registry name 列挙。 */
export function listRegistryNames() {
  return Array.from(REGISTRY_META.keys())
}
