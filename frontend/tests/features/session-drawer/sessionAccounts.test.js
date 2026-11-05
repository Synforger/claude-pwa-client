import { describe, it, expect } from 'vitest'
import { accountChanges } from '../../../src/features/session-drawer/sessionAccounts.js'

describe('accountChanges', () => {
  const sessions = [
    { id: 'ses_a', account_id: 'company', fallback_from: null, account_pinned: false },
    { id: 'ses_b', account_id: 'personal', fallback_from: 'company', account_pinned: false },
    { id: 'ses_c' },
  ]

  it('names the fields of a tab the client moved to another account', () => {
    const payload = { ses_a: { account_id: 'personal', fallback_from: 'company', account_pinned: false } }
    expect(accountChanges(sessions, payload)).toEqual([['ses_a', { account_id: 'personal', fallback_from: 'company' }]])
  })

  it('names the tab that went back to its own account', () => {
    const payload = { ses_b: { account_id: 'company', fallback_from: null, account_pinned: false } }
    expect(accountChanges(sessions, payload)).toEqual([['ses_b', { account_id: 'company', fallback_from: null }]])
  })

  it('names nothing when every row already shows what the snapshot says', () => {
    const payload = {
      ses_a: { account_id: 'company', fallback_from: null, account_pinned: false },
      ses_b: { account_id: 'personal', fallback_from: 'company', account_pinned: false },
    }
    expect(accountChanges(sessions, payload)).toEqual([])
  })

  it('takes an unset field of a row and a null of the snapshot for the same thing', () => {
    const payload = { ses_c: { account_id: null, fallback_from: null, account_pinned: false } }
    expect(accountChanges(sessions, payload)).toEqual([])
  })

  it('names the hold on an account when it is set', () => {
    expect(accountChanges(sessions, { ses_a: { account_pinned: true } })).toEqual([['ses_a', { account_pinned: true }]])
  })

  it('leaves a tab alone when the snapshot says nothing about its account', () => {
    const payload = { ses_a: { busy: false }, ses_b: {}, ses_c: null }
    expect(accountChanges(sessions, payload)).toEqual([])
  })

  it('ignores a tab the list does not have, and takes a missing snapshot for nothing to change', () => {
    expect(accountChanges(sessions, { ses_z: { account_id: 'personal' } })).toEqual([])
    expect(accountChanges(sessions, undefined)).toEqual([])
  })
})
