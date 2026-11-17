import { describe, it, expect } from 'vitest'
import { accountChanges, accountLabelOf } from '../../../src/features/session-drawer/sessionAccounts.js'

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

describe('accountChanges for the account a sleeping tab wakes on', () => {
  it('names the account a tab wakes on when the snapshot says it changed', () => {
    const sessions = [{ id: 'ses_a', account_id: 'personal', account_on_wake: 'personal' }]
    expect(accountChanges(sessions, { ses_a: { account_on_wake: 'work' } })).toEqual([['ses_a', { account_on_wake: 'work' }]])
  })

  it('clears it when the tab woke up (= null in the snapshot)', () => {
    const sessions = [{ id: 'ses_a', account_id: 'personal', account_on_wake: 'work' }]
    expect(accountChanges(sessions, { ses_a: { account_on_wake: null } })).toEqual([['ses_a', { account_on_wake: null }]])
  })

  it('takes an unset field of a row and a null of the snapshot for the same thing', () => {
    expect(accountChanges([{ id: 'ses_a' }], { ses_a: { account_on_wake: null } })).toEqual([])
  })
})

describe('accountLabelOf', () => {
  const accounts = [{ id: 'personal', display_name: 'Personal' }, { id: 'work', display_name: 'Work' }]

  it('shows only the account a sleeping tab wakes on, not the one it last ran on', () => {
    expect(accountLabelOf({ account_id: 'personal', account_on_wake: 'work' }, accounts, null)).toBe('Work')
    expect(accountLabelOf({ account_id: 'work', account_on_wake: 'personal' }, accounts, null)).toBe('Personal')
  })

  it('shows the account it runs on when it wakes on the same one, or when it is awake', () => {
    expect(accountLabelOf({ account_id: 'work', account_on_wake: 'work' }, accounts, null)).toBe('Work')
    expect(accountLabelOf({ account_id: 'work', account_on_wake: null }, accounts, null)).toBe('Work')
    expect(accountLabelOf({ account_id: 'work' }, accounts, null)).toBe('Work')
  })

  it('takes the default account for a row with no account', () => {
    expect(accountLabelOf({}, accounts, 'personal')).toBe('Personal')
    expect(accountLabelOf({ account_on_wake: 'work' }, accounts, 'personal')).toBe('Work')
  })

  it('shows no label with one account configured', () => {
    expect(accountLabelOf({ account_id: 'personal', account_on_wake: 'work' }, [accounts[0]], null)).toBeNull()
  })

  it('falls back to the id of an account the list does not know', () => {
    expect(accountLabelOf({ account_id: 'gone' }, accounts, null)).toBe('gone')
  })
})
