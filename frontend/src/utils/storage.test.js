import { describe, it, expect, beforeEach, vi } from 'vitest'
import { lsGet, lsSet, lsRemove, lsSetDebounced, lsFlushDebounced, __lsResetDebounced } from './storage.js'

// localStorage を in-memory スタブで差し替える (= jsdom 環境に依存せず node で完結)。
function makeLocalStorage() {
  let store = {}
  return {
    getItem: (k) => (k in store ? store[k] : null),
    setItem: (k, v) => { store[k] = String(v) },
    removeItem: (k) => { delete store[k] },
    clear: () => { store = {} },
  }
}

beforeEach(() => {
  vi.stubGlobal('localStorage', makeLocalStorage())
  __lsResetDebounced()
})

describe('storage helpers (lsGet / lsSet / lsRemove)', () => {
  it('lsGet returns parsed JSON', () => {
    localStorage.setItem('k', JSON.stringify({ a: 1 }))
    expect(lsGet('k')).toEqual({ a: 1 })
  })

  it('lsGet returns the fallback for a missing key', () => {
    expect(lsGet('missing', [])).toEqual([])
    expect(lsGet('missing')).toBeNull()
  })

  it('lsGet returns the fallback for corrupt JSON (= 例外を握りつぶす)', () => {
    localStorage.setItem('bad', '{not json')
    expect(lsGet('bad', {})).toEqual({})
  })

  it('lsSet round-trips through lsGet', () => {
    lsSet('k', { x: [1, 2] })
    expect(lsGet('k')).toEqual({ x: [1, 2] })
  })

  it('lsRemove deletes the key', () => {
    lsSet('k', 1)
    lsRemove('k')
    expect(lsGet('k', 'gone')).toBe('gone')
  })
})

describe('lsSetDebounced / lsFlushDebounced', () => {
  beforeEach(() => { vi.useFakeTimers() })

  it('debounces multiple writes to the same key (= last wins)', () => {
    lsSetDebounced('k', 1)
    lsSetDebounced('k', 2)
    lsSetDebounced('k', 3)
    expect(lsGet('k')).toBeNull() // まだ commit されてない
    vi.advanceTimersByTime(600)
    expect(lsGet('k')).toBe(3)
  })

  it('lsFlushDebounced(key) commits immediately', () => {
    lsSetDebounced('k', { a: 1 })
    lsFlushDebounced('k')
    expect(lsGet('k')).toEqual({ a: 1 })
  })

  it('lsFlushDebounced() (= no arg) commits all pending keys', () => {
    lsSetDebounced('a', 1)
    lsSetDebounced('b', 2)
    lsFlushDebounced()
    expect(lsGet('a')).toBe(1)
    expect(lsGet('b')).toBe(2)
  })

  it('uses custom delay', () => {
    lsSetDebounced('k', 'v', 100)
    vi.advanceTimersByTime(50)
    expect(lsGet('k')).toBeNull()
    vi.advanceTimersByTime(60)
    expect(lsGet('k')).toBe('v')
  })
})
