// 🧩 のタップで開く拡張の決め方と、 最後に開いた拡張の保存の検査。
import { describe, it, expect, beforeEach } from 'vitest'
import { nextOpenOnTap, loadLastId, saveLastId } from './slotTap.js'

const store = new Map()
globalThis.localStorage = {
  getItem: (k) => (store.has(k) ? store.get(k) : null),
  setItem: (k, v) => { store.set(k, String(v)) },
  removeItem: (k) => { store.delete(k) },
}

const ext = (id) => ({ id, title: id, icon: '🧩', path: `/ext/${id}/` })

describe('features/extensions — one-tap slot', () => {
  beforeEach(() => store.clear())

  it('opens the last used extension, or the first one when none was used', () => {
    expect(nextOpenOnTap([ext('a'), ext('b')], null, 'b')).toBe('b')
    expect(nextOpenOnTap([ext('a'), ext('b')], null, null)).toBe('a')
  })

  it('falls back to the first one when the last used is no longer reachable', () => {
    expect(nextOpenOnTap([ext('a'), ext('b')], null, 'gone')).toBe('a')
  })

  it('collapses whatever is open', () => {
    expect(nextOpenOnTap([ext('a'), ext('b')], 'a', 'b')).toBe(null)
  })

  it('opens something when the open id is not one of the reachable extensions', () => {
    expect(nextOpenOnTap([ext('a')], 'gone', null)).toBe('a')
  })

  it('does nothing without extensions', () => {
    expect(nextOpenOnTap([], null, 'a')).toBe(null)
    expect(nextOpenOnTap(undefined, null, null)).toBe(null)
  })

  it('remembers the last used extension per device', () => {
    expect(loadLastId()).toBe(null)
    saveLastId('b')
    expect(loadLastId()).toBe('b')
    store.set('cpc.extensions.lastId', '42')
    expect(loadLastId()).toBe(null)
  })
})
