// The place that holds a conversation's message list to MAX_MESSAGES: which messages go, and which lists are left alone.
import { describe, it, expect } from 'vitest'
import { dropOldestMessages, clampMessageDict } from '../../../src/features/chat/clampMessages.js'

const message = (id, ts) => ({ id, role: 'agent', text: id, ...(ts === undefined ? {} : { ts }) })

describe('dropOldestMessages', () => {
  it('a list within the limit is returned as it is (the same array)', () => {
    const list = [message('a', 1), message('b', 2)]
    expect(dropOldestMessages(list, 2)).toBe(list)
  })

  it('drops the oldest by time, not by position in the array (a replay of the history appends old rows at the end)', () => {
    const list = [message('new1', 100), message('new2', 101), message('old1', 1), message('old2', 2)]
    const kept = dropOldestMessages(list, 2)
    expect(kept.map(m => m.id)).toEqual(['new1', 'new2'])
  })

  it('what stays keeps its order in the array', () => {
    const list = [message('c', 30), message('a', 10), message('d', 40), message('b', 20)]
    expect(dropOldestMessages(list, 3).map(m => m.id)).toEqual(['c', 'd', 'b'])
  })

  it('a message without a time stays next to the latest one (it is the message just sent or just started)', () => {
    const list = [message('m1', 1), message('m2', 2), message('typing'), message('m3', 3)]
    expect(dropOldestMessages(list, 2).map(m => m.id)).toEqual(['typing', 'm3'])
  })

  it('does not take what is not an array', () => {
    expect(dropOldestMessages(undefined, 2)).toBeUndefined()
  })
})

describe('clampMessageDict', () => {
  const list = (n, prefix) => Array.from({ length: n }, (_, i) => message(`${prefix}${i}`, i))

  it('cuts the conversation that changed and leaves the other as it is', () => {
    const quiet = list(3, 'q')
    const prev = { a: list(4, 'a'), b: quiet }
    const next = { a: [...prev.a, message('a-new', 99)], b: quiet }
    const out = clampMessageDict(prev, next, 4)
    expect(out.a.map(m => m.id)).toEqual(['a1', 'a2', 'a3', 'a-new'])
    expect(out.b).toBe(quiet)
  })

  it('a conversation whose array is the one it was is not looked at, however long it is', () => {
    const long = list(10, 'x')
    const prev = { a: long }
    const next = { a: long, b: list(2, 'b') }
    expect(clampMessageDict(prev, next, 4).a).toBe(long)
  })

  it('the same object comes back when nothing is cut', () => {
    const prev = { a: list(2, 'a') }
    const next = { a: [...prev.a, message('n', 9)] }
    expect(clampMessageDict(prev, next, 5)).toBe(next)
    expect(clampMessageDict(prev, prev, 1)).toBe(prev)
  })
})
