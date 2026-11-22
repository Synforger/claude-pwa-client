import { describe, expect, it } from 'vitest'
import { holdUserBubble } from '../../../src/features/chat/holdUserBubble.js'

describe('holdUserBubble', () => {
  it('marks the kept text and takes the empty answer bubble away', () => {
    const next = holdUserBubble([{ id: 'u', role: 'user', text: 'hi' }, { id: 'a', role: 'agent', streaming: true }], m => m.id === 'u')
    expect(next).toEqual([{ id: 'u', role: 'user', text: 'hi', heldByWindow: true }])
  })

  it('leaves a bubble the record already confirmed', () => {
    expect(holdUserBubble([{ id: 'u', role: 'user', uuid: 'x' }], m => m.id === 'u')).toBeNull()
  })
})
