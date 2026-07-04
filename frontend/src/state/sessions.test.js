import { describe, it, expect, beforeEach } from 'vitest'
import {
  getSnapshot,
  setSessions,
  setActiveId,
  appendSession,
  removeSession,
  patchSession,
  setSessionActivity,
  setUnreadDone,
  clearUnreadDone,
  hydrate,
} from './sessions.js'

// Phase J-1 (= 2026-06-29、 ADR-026 末尾「将来 task」 1 件目) の contract test。
// 旧実装は内部で `.sid !== sid` で filter していたため、 runtime の Session オブジェクト
// (= `.id` キー) を渡すと `removeSession` / `patchSession` が事実上 no-op だった (= dead code 化)。
// 本 test は store setter が `.id` キーで動くこと、 `.sid` 古キーでは no-op (= 取り違え検知) を保証する。

// store は module singleton なので各 test の前に空に戻す。
function reset() {
  hydrate({
    sessions: [],
    activeId: null,
    agents: [],
    sessionActivity: {},
    unreadDone: {},
  })
}

describe('state/sessions.js setter contract (unified on the .id key)', () => {
  beforeEach(() => { reset() })

  it('removeSession deletes by the .id key and cascades cleanup of activity/unread', () => {
    setSessions([
      { id: 'a', title: 'A' },
      { id: 'b', title: 'B' },
    ])
    setSessionActivity('a', { length: 3, ts: 100 })
    setUnreadDone('a', true)

    removeSession('a')

    const snap = getSnapshot()
    expect(snap.sessions).toEqual([{ id: 'b', title: 'B' }])
    expect(snap.sessionActivity).not.toHaveProperty('a')
    expect(snap.unreadDone).not.toHaveProperty('a')
  })

  it('removeSession no-ops for a missing id (same snapshot reference)', () => {
    setSessions([{ id: 'a', title: 'A' }])
    const before = getSnapshot()
    removeSession('does-not-exist')
    expect(getSnapshot()).toBe(before)
  })

  it('removeSession cannot delete via a legacy .sid-keyed object (proof that .id is the contractual key)', () => {
    // 旧 backend response shape (= sid フィールド) を模擬して入れた場合、 store は `.id` で
    // 判定するため見つからず no-op になる。 これが正しい挙動 (= runtime は `.id` 一本)。
    setSessions([{ sid: 'legacy-1', title: 'legacy' }])
    const before = getSnapshot()
    removeSession('legacy-1')
    expect(getSnapshot()).toBe(before)
  })

  it('patchSession updates the session by the .id key', () => {
    setSessions([
      { id: 'a', title: 'A', notify_mode: 'always' },
      { id: 'b', title: 'B' },
    ])
    patchSession('a', { title: 'A2', notify_mode: 'never' })

    const snap = getSnapshot()
    expect(snap.sessions[0]).toEqual({ id: 'a', title: 'A2', notify_mode: 'never' })
    expect(snap.sessions[1]).toEqual({ id: 'b', title: 'B' })
  })

  it('patchSession no-ops for a missing id', () => {
    setSessions([{ id: 'a', title: 'A' }])
    const before = getSnapshot()
    patchSession('missing', { title: 'X' })
    expect(getSnapshot()).toBe(before)
  })

  it('appendSession inserts at the head without touching existing sessions', () => {
    setSessions([{ id: 'a', title: 'A' }])
    appendSession({ id: 'b', title: 'B' })
    expect(getSnapshot().sessions).toEqual([
      { id: 'b', title: 'B' },
      { id: 'a', title: 'A' },
    ])
  })

  it('setActiveId keeps the snapshot reference for the same value (contract: no subscriber notification)', () => {
    setActiveId('a')
    const snap1 = getSnapshot()
    setActiveId('a')
    expect(getSnapshot()).toBe(snap1)
    setActiveId('b')
    expect(getSnapshot()).not.toBe(snap1)
    expect(getSnapshot().activeId).toBe('b')
  })

  it('clearUnreadDone removes a registered key and no-ops for unknown keys', () => {
    setUnreadDone('a', true)
    setUnreadDone('b', true)
    clearUnreadDone('a')
    expect(getSnapshot().unreadDone).toEqual({ b: true })

    const before = getSnapshot()
    clearUnreadDone('does-not-exist')
    expect(getSnapshot()).toBe(before)
  })
})
