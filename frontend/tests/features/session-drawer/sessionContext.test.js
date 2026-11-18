// How the list follows the context amount of an API tab from one overview snapshot (`sessionContext.js`).
import { describe, it, expect } from 'vitest'
import { contextChanges } from '../../../src/features/session-drawer/sessionContext.js'

describe('contextChanges', () => {
  const sessions = [
    { id: 'api_support-bot', kind: 'api', context_tokens: 12300 },
    { id: 'api_other', kind: 'api' },
    { id: 'ses_a' },
  ]

  it('names the tab whose amount grew', () => {
    expect(contextChanges(sessions, { 'api_support-bot': { context_tokens: 15000 } })).toEqual([['api_support-bot', 15000]])
  })

  it('names the amount of a tab whose row had none yet, and the tab whose amount went away', () => {
    expect(contextChanges(sessions, { api_other: { context_tokens: 400 } })).toEqual([['api_other', 400]])
    expect(contextChanges(sessions, { 'api_support-bot': { context_tokens: null } })).toEqual([['api_support-bot', null]])
  })

  it('names nothing when every row already shows what the snapshot says', () => {
    expect(contextChanges(sessions, { 'api_support-bot': { context_tokens: 12300 }, api_other: { context_tokens: null } })).toEqual([])
  })

  it('leaves alone a tab the snapshot says nothing about, and a Claude tab whose entry has no amount', () => {
    expect(contextChanges(sessions, { ses_a: { busy: false } })).toEqual([])
    expect(contextChanges(sessions, {})).toEqual([])
    expect(contextChanges(sessions, undefined)).toEqual([])
  })
})
