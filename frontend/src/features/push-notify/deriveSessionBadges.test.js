// deriveSessionBadges の waitingInput 合流 (= 2026-07-15 裏セッション質問待ちバッジ)。
import { describe, it, expect } from 'vitest'
import { deriveSessionBadges } from './useSessionBadges.js'

describe('deriveSessionBadges waitingInput', () => {
  it('messages が空でも waitingInput=true の裏 sid に ? バッジが点く', () => {
    const { sessionBadges } = deriveSessionBadges({
      sids: ['a', 'b'], activeSid: 'a',
      messages: {}, loading: {}, unreadDone: {},
      waitingInput: { b: true },
    })
    expect(sessionBadges.b).toEqual({ kind: 'pending', label: '?' })
    expect(sessionBadges.a).toBe(null)  // active は常に null
  })

  it('waitingInput 無指定でも従来の messages 由来判定は生きる (= 後方互換)', () => {
    const { sessionBadges } = deriveSessionBadges({
      sids: ['b'], activeSid: 'a',
      messages: { b: [{ askUserQuestion: { answered: false } }] },
      loading: {}, unreadDone: {},
    })
    expect(sessionBadges.b).toEqual({ kind: 'pending', label: '?' })
  })
})
