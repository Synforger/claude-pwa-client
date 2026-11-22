// How the list follows a tab's title and an API tab's context from one overview snapshot (`sessionContext.js`).
import { describe, it, expect } from 'vitest'
import { listRowChanges } from '../../../src/features/session-drawer/sessionContext.js'

describe('listRowChanges', () => {
  const sessions = [
    { id: 'api_support-bot', kind: 'api', context_tokens: 12300, context_window: null },
    { id: 'api_other', kind: 'api' },
    { id: 'api_g-abc', kind: 'api', context_tokens: 4800, context_window: 100000 },
    { id: 'ses_a' },
  ]

  it('names the tab whose amount grew, with both figures', () => {
    expect(listRowChanges(sessions, { 'api_support-bot': { context_tokens: 15000, context_window: null } }))
      .toEqual([['api_support-bot', { context_tokens: 15000, context_window: null }]])
  })

  it('names the amount of a tab whose row had none yet, and the tab whose amount went away', () => {
    expect(listRowChanges(sessions, { api_other: { context_tokens: 400 } }))
      .toEqual([['api_other', { context_tokens: 400, context_window: null }]])
    expect(listRowChanges(sessions, { 'api_support-bot': { context_tokens: null } }))
      .toEqual([['api_support-bot', { context_tokens: null, context_window: null }]])
  })

  it('names the tab its source renamed, and leaves the title alone when the entry has none', () => {
    expect(listRowChanges(sessions, { 'api_g-abc': { title: 'Trip', context_tokens: 4800, context_window: 100000 } }))
      .toEqual([['api_g-abc', { title: 'Trip', context_tokens: 4800, context_window: 100000 }]])
  })

  it('names the tab whose window changed while its amount stayed', () => {
    expect(listRowChanges(sessions, { 'api_g-abc': { context_tokens: 4800, context_window: 200000 } }))
      .toEqual([['api_g-abc', { context_tokens: 4800, context_window: 200000 }]])
  })

  it('names nothing when every row already shows what the snapshot says', () => {
    expect(listRowChanges(sessions, {
      'api_support-bot': { context_tokens: 12300, context_window: null },
      api_other: { context_tokens: null },
      'api_g-abc': { context_tokens: 4800, context_window: 100000 },
    })).toEqual([])
  })

  it('names a Claude tab that was renamed elsewhere, with its title alone', () => {
    expect(listRowChanges(sessions, { ses_a: { busy: false, title: 'Index the people' } }))
      .toEqual([['ses_a', { title: 'Index the people' }]])
    expect(listRowChanges([{ id: 'ses_a', title: 'same' }], { ses_a: { title: 'same' } })).toEqual([])
  })

  it('leaves alone a tab the snapshot says nothing about, and a Claude tab whose entry has no amount', () => {
    expect(listRowChanges(sessions, { ses_a: { busy: false } })).toEqual([])
    expect(listRowChanges(sessions, {})).toEqual([])
    expect(listRowChanges(sessions, undefined)).toEqual([])
  })
})
