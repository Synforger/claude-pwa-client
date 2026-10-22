import { describe, expect, it } from 'vitest'
import { sameSessionIds } from '../../../src/features/session-drawer/sessionIds.js'

describe('sameSessionIds', () => {
  const sessions = [{ id: 'ses_a' }, { id: 'ses_b' }]

  it('is the same set whatever the order', () => {
    expect(sameSessionIds(['ses_b', 'ses_a'], sessions)).toBe(true)
  })

  it('sees a tab another place opened', () => {
    expect(sameSessionIds(['ses_a', 'ses_b', 'ses_c'], sessions)).toBe(false)
  })

  it('sees a tab another place closed', () => {
    expect(sameSessionIds(['ses_a'], sessions)).toBe(false)
  })

  it('sees one tab swapped for another', () => {
    expect(sameSessionIds(['ses_a', 'ses_c'], sessions)).toBe(false)
  })
})
