import { describe, it, expect } from 'vitest'
import { isPersistableMessage } from './useChatStorage.js'

// 2026-06-24 server-of-truth 純化: localStorage 永続化境界の唯一の真値となる純関数 test。
// 重複バグ root cause (= uuid なし user 行が ghost として復活し SSE event との dedup を破る)
// の構造的根治はここで保証される。 reconcileUserMessage 側の dedup 簡素化と対になる境界。

describe('isPersistableMessage', () => {
  it('uuid 付き確定 user は通る', () => {
    expect(isPersistableMessage({ role: 'user', text: 'hi', uuid: 'u1' })).toBe(true)
  })

  it('optimistic user は弾く (= ephemeral 描画専用)', () => {
    expect(isPersistableMessage({ role: 'user', text: 'hi', uuid: 'u1', optimistic: true })).toBe(false)
  })

  it('sendFailed user は弾く (= 再送待ち ephemeral、 localStorage に書くと ghost 化)', () => {
    expect(isPersistableMessage({ role: 'user', text: 'hi', uuid: 'u1', sendFailed: true })).toBe(false)
  })

  it('uuid 欠落 user は弾く (= 重複表示の root cause、 旧キャッシュ自動掃除も兼ねる)', () => {
    expect(isPersistableMessage({ role: 'user', text: 'hi' })).toBe(false)
    expect(isPersistableMessage({ role: 'user', text: 'hi', uuid: null })).toBe(false)
    expect(isPersistableMessage({ role: 'user', text: 'hi', uuid: '' })).toBe(false)
  })

  it('agent message は uuid 有無に関係なく通る (= streaming 中も persist 対象)', () => {
    expect(isPersistableMessage({ role: 'agent', text: 'reply', uuid: 'a1' })).toBe(true)
    expect(isPersistableMessage({ role: 'agent', text: 'reply' })).toBe(true)
    expect(isPersistableMessage({ role: 'agent', text: '', streaming: true })).toBe(true)
  })

  it('system message (= session_end マーカー等) は通る', () => {
    expect(isPersistableMessage({ role: 'system', kind: 'session_end', ts: 1 })).toBe(true)
  })

  it('null / undefined は弾く', () => {
    expect(isPersistableMessage(null)).toBe(false)
    expect(isPersistableMessage(undefined)).toBe(false)
  })
})
