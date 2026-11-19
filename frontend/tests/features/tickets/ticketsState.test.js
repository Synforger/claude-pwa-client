import { describe, it, expect, beforeEach } from 'vitest'
import { applyTicketsSnapshot, getSnapshot, setAnswerDraft } from '../../../src/state/tickets.js'

beforeEach(() => {
  applyTicketsSnapshot({ tickets: [], peers: {} })
  setAnswerDraft('home-1', '', '')
})

describe('state/tickets', () => {
  it('takes a picture of the tickets and the other machines', () => {
    applyTicketsSnapshot({ tickets: [{ id: 'home-1' }], peers: { company: { waiting: 1 } } })
    expect(getSnapshot()).toMatchObject({ loaded: true, tickets: [{ id: 'home-1' }], peers: { company: { waiting: 1 } } })
  })

  it('leaves what it has when a picture is malformed (= an old screen and a new backend, or the reverse)', () => {
    applyTicketsSnapshot({ tickets: [{ id: 'home-1' }], peers: {} })
    applyTicketsSnapshot(null)
    applyTicketsSnapshot({ tickets: 'x' })
    expect(getSnapshot().tickets).toEqual([{ id: 'home-1' }])
  })

  it('keeps a draft with the question it is for, and drops it when it is emptied', () => {
    setAnswerDraft('home-1', 'asked-1', 'half')
    expect(getSnapshot().answerDrafts['home-1']).toEqual({ askedAt: 'asked-1', text: 'half' })
    setAnswerDraft('home-1', 'asked-1', '')
    expect(getSnapshot().answerDrafts['home-1']).toBeUndefined()
  })
})
