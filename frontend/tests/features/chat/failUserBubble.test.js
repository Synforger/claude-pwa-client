// A sent bubble that did not reach Claude (`failUserBubble`): picked by the send's id or the bubble's id, marked, and
// the empty "thinking" bubble behind it dropped.
import { describe, it, expect } from 'vitest'
import { failUserBubble } from '../../../src/features/chat/failUserBubble.js'

const sent = { id: 'b1', send_id: 's1', role: 'user', text: 'hello', optimistic: true }
const thinking = { id: 'a1', role: 'agent', text: '', tools: [], streaming: true }

describe('failUserBubble', () => {
  it('marks the bubble of the send and drops the empty answer behind it', () => {
    const failed = failUserBubble([sent, thinking], m => m.send_id === 's1')
    expect(failed.text).toBe('hello')
    expect(failed.next).toEqual([{ ...sent, sendFailed: true }])
  })

  it('marks a bubble restored from storage, which waits for its confirmation without the optimistic flag', () => {
    const restored = { id: 'b1', send_id: 's1', role: 'user', text: 'hello' }
    expect(failUserBubble([restored], m => m.send_id === 's1').next[0].sendFailed).toBe(true)
  })

  it('leaves a bubble the record confirmed', () => {
    expect(failUserBubble([{ ...sent, optimistic: false, uuid: 'u1' }], m => m.send_id === 's1')).toBeNull()
  })

  it('leaves a bubble marked before', () => {
    expect(failUserBubble([{ ...sent, sendFailed: true }], m => m.send_id === 's1')).toBeNull()
  })

  it('finds nothing for another send', () => {
    expect(failUserBubble([sent, thinking], m => m.send_id === 's2')).toBeNull()
  })

  it('keeps an answer that has begun', () => {
    const answering = { ...thinking, text: 'Let me' }
    expect(failUserBubble([sent, answering], m => m.send_id === 's1').next).toHaveLength(2)
  })
})
