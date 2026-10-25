import { describe, it, expect } from 'vitest'
import { treeReport } from '../../../src/features/session-drawer/treeReport.js'

describe('treeReport', () => {
  it('counts the tabs, the tabs with a tier, and the folders the tree made', () => {
    const sessions = [
      { id: 'ses_a', tier: 'normal' },
      { id: 'ses_b', tier: 'projects/Platform' },
      { id: 'ses_c', tier: null },
      { id: 'ses_d' },
    ]
    const rows = [
      { kind: 'session', session: sessions[0] },
      { kind: 'folder', key: '/Platform' },
      { kind: 'session', session: sessions[1] },
    ]
    expect(treeReport({ build: 'abc123', sessions, rows })).toEqual({
      stage: 'drawer:tree',
      build: 'abc123',
      sessionCount: 4,
      withTierCount: 2,
      folderCount: 1,
      tiers: { ses_a: 'normal', ses_b: 'projects/Platform', ses_c: null, ses_d: null },
    })
  })
})
