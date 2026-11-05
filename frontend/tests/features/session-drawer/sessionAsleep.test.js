import { describe, it, expect } from 'vitest'
import { asleepChanges } from '../../../src/features/session-drawer/sessionAsleep.js'

describe('asleepChanges', () => {
  const sessions = [
    { id: 'ses_a', asleep: false },
    { id: 'ses_b', asleep: true },
    { id: 'ses_c' },
  ]

  it('names the tabs that went to sleep and the tabs that woke up', () => {
    const payload = { ses_a: { asleep: true }, ses_b: { asleep: false }, ses_c: { asleep: true } }
    expect(asleepChanges(sessions, payload)).toEqual([['ses_a', true], ['ses_b', false], ['ses_c', true]])
  })

  it('names nothing when every tab already shows what the snapshot says', () => {
    const payload = { ses_a: { asleep: false }, ses_b: { asleep: true }, ses_c: { asleep: false } }
    expect(asleepChanges(sessions, payload)).toEqual([])
  })

  it('leaves a tab alone when the snapshot says nothing about whether it sleeps', () => {
    const payload = { ses_a: { busy: false }, ses_b: {}, ses_c: null }
    expect(asleepChanges(sessions, payload)).toEqual([])
  })

  it('ignores a tab the list does not have', () => {
    expect(asleepChanges(sessions, { ses_z: { asleep: true } })).toEqual([])
  })

  it('takes a missing snapshot for nothing to change', () => {
    expect(asleepChanges(sessions, undefined)).toEqual([])
  })
})
