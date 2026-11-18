// displayWindowStart (= where the chat window starts in the list of messages) and the key it is frozen on.
//
// At the bottom the window is the last DISPLAY_LIMIT messages. While the user reads above the bottom it is frozen on the
// message that was its first one, so that what is read does not shift as new messages come. The conversation is held at
// MAX_MESSAGES, so a message is dropped off the top whenever a new one comes: the window is kept by the message, not by
// its number in the list.
import { describe, it, expect } from 'vitest'
import { displayWindowStart, messageKey } from '../../src/layout/ChatPanel.jsx'
import { clampMessageDict } from '../../src/features/chat/clampMessages.js'
import { MAX_MESSAGES } from '../../src/_common/constants.js'

const list = (count, from = 0) => Array.from({ length: count }, (_, i) => ({ id: `m${from + i}`, role: 'agent', text: 'x', ts: 1000 + from + i }))

describe('displayWindowStart', () => {
  it('at the bottom (not frozen) the window is the last `limit` messages', () => {
    expect(displayWindowStart(list(50), null, 100)).toBe(0)
    expect(displayWindowStart(list(100), null, 100)).toBe(0)
    expect(displayWindowStart(list(150), null, 100)).toBe(50)
    expect(displayWindowStart(list(150), undefined, 100)).toBe(50)
  })

  it('frozen: the window starts at the message it froze on, and only grows toward the newest', () => {
    const frozenOn = messageKey(list(150)[50])               // the first message of the window when it froze
    expect(displayWindowStart(list(180), frozenOn, 100)).toBe(50)   // 30 new messages: not 80
  })

  it('frozen: when old messages are dropped off the top the start stays on the same message', () => {
    // 200 messages, frozen on m100. Ten new messages come and the ten oldest go: m100 is now at 90.
    const frozenOn = 'm100'
    const after = list(200, 10)
    expect(after[90].id).toBe('m100')
    expect(displayWindowStart(after, frozenOn, 100)).toBe(90)
  })

  it('frozen: when the message it froze on has been dropped, the window starts at the oldest that is left', () => {
    expect(displayWindowStart(list(200, 150), 'm100', 100)).toBe(0)
  })

  it('frozen: the start is never past the last `limit` messages (the window is not shorter than the limit)', () => {
    expect(displayWindowStart(list(120), 'm50', 100)).toBe(20)
    expect(displayWindowStart(list(40), 'm50', 100)).toBe(0)
  })

  it('a message is known by its id, else its uuid', () => {
    expect(messageKey({ id: 'a', uuid: 'b' })).toBe('a')
    expect(messageKey({ uuid: 'b' })).toBe('b')
    expect(messageKey({})).toBeNull()
    expect(messageKey(undefined)).toBeNull()
  })
})

describe('the window while a full conversation keeps receiving messages (with the conversation held at MAX_MESSAGES)', () => {
  // The conversation is full (MAX_MESSAGES), the user scrolls up and the window freezes on its first message; then
  // new messages keep coming, each one dropping the oldest. This is what made what was being read move up with every
  // new message, when the window was remembered by a number.
  const grow = (messages, count) => {
    let prev = { s: messages }
    for (let i = 0; i < count; i++) {
      const next = { s: [...prev.s, { id: `n${i}`, role: 'agent', text: 'x', ts: 5000 + i }] }
      prev = clampMessageDict(prev, next)
    }
    return prev.s
  }

  it('the first message of the window does not change for as long as it is in the list', () => {
    const full = list(MAX_MESSAGES)
    const frozenOn = messageKey(full[MAX_MESSAGES - 100])    // frozen when the window was the last 100
    for (const newMessages of [1, 40, 99]) {
      const now = grow(full, newMessages)
      expect(now).toHaveLength(MAX_MESSAGES)
      const start = displayWindowStart(now, frozenOn, 100)
      expect(now[start].id).toBe(frozenOn)
    }
  })

  it('the window starts at the oldest message left once the one it froze on is dropped', () => {
    const full = list(MAX_MESSAGES)
    const frozenOn = messageKey(full[MAX_MESSAGES - 100])
    const now = grow(full, 101)                              // the 101st new message drops the frozen one
    expect(now.some(m => m.id === frozenOn)).toBe(false)
    expect(displayWindowStart(now, frozenOn, 100)).toBe(0)
  })

  it('the window never holds more than MAX_MESSAGES', () => {
    const full = list(MAX_MESSAGES)
    const frozenOn = messageKey(full[MAX_MESSAGES - 100])
    const now = grow(full, 300)
    const start = displayWindowStart(now, frozenOn, 100)
    expect(now.slice(start).length).toBeLessThanOrEqual(MAX_MESSAGES)
  })
})
