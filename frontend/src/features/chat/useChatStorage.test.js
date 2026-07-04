import { describe, it, expect } from 'vitest'
import { isPersistableMessage } from './useChatStorage.js'

// 2026-06-24 server-of-truth 純化: localStorage 永続化境界の唯一の真値となる純関数 test。
// 重複バグ root cause (= uuid なし user 行が ghost として復活し SSE event との dedup を破る)
// の構造的根治はここで保証される。 reconcileUserMessage 側の dedup 簡素化と対になる境界。

describe('isPersistableMessage', () => {
  it('confirmed user with a uuid passes', () => {
    expect(isPersistableMessage({ role: 'user', text: 'hi', uuid: 'u1' })).toBe(true)
  })

  it('optimistic user is rejected (ephemeral, render-only)', () => {
    expect(isPersistableMessage({ role: 'user', text: 'hi', uuid: 'u1', optimistic: true })).toBe(false)
  })

  it('sendFailed user is rejected (ephemeral awaiting resend; persisting it creates ghosts)', () => {
    expect(isPersistableMessage({ role: 'user', text: 'hi', uuid: 'u1', sendFailed: true })).toBe(false)
  })

  it('user without a uuid is rejected (duplicate-display root cause; also auto-cleans old caches)', () => {
    expect(isPersistableMessage({ role: 'user', text: 'hi' })).toBe(false)
    expect(isPersistableMessage({ role: 'user', text: 'hi', uuid: null })).toBe(false)
    expect(isPersistableMessage({ role: 'user', text: 'hi', uuid: '' })).toBe(false)
  })

  it('agent messages pass with or without a uuid (persisted even while streaming)', () => {
    expect(isPersistableMessage({ role: 'agent', text: 'reply', uuid: 'a1' })).toBe(true)
    expect(isPersistableMessage({ role: 'agent', text: 'reply' })).toBe(true)
    expect(isPersistableMessage({ role: 'agent', text: '', streaming: true })).toBe(true)
  })

  it('system messages (session_end markers etc.) pass', () => {
    expect(isPersistableMessage({ role: 'system', kind: 'session_end', ts: 1 })).toBe(true)
  })

  it('null / undefined are rejected', () => {
    expect(isPersistableMessage(null)).toBe(false)
    expect(isPersistableMessage(undefined)).toBe(false)
  })
})
