// @vitest-environment jsdom
// statusCache (= all-status の起動時 hydrate cache) の契約 test。
// 旧 sse-sessions-status.test.js から移行 (= 2026-07-27 legacy transport 退役)。
import { it, expect, beforeEach, vi } from 'vitest'
import { getCachedAllStatus, LS_STATUS_KEY } from './statusCache.ts'

// jsdom 環境で localStorage が未定義になる構成があるため in-memory mock を明示 stub する。
function makeStorage() {
  const m = new Map()
  return {
    getItem: k => (m.has(k) ? m.get(k) : null),
    setItem: (k, v) => m.set(k, String(v)),
    removeItem: k => m.delete(k),
    clear: () => m.clear(),
  }
}

beforeEach(() => {
  vi.stubGlobal('localStorage', makeStorage())
})

it('returns the cached payload when present', () => {
  localStorage.setItem(LS_STATUS_KEY, JSON.stringify({ ses_a: { model: 'm' } }))
  expect(getCachedAllStatus()).toEqual({ ses_a: { model: 'm' } })
})

it('returns {} when the cache is empty', () => {
  expect(getCachedAllStatus()).toEqual({})
})

it('returns {} on corrupt json instead of throwing', () => {
  localStorage.setItem(LS_STATUS_KEY, '{not json')
  expect(getCachedAllStatus()).toEqual({})
})
