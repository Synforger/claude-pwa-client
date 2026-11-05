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
      trigger: 'open',
      build: 'abc123',
      sessionCount: 4,
      withTierCount: 2,
      childCount: 0,
      agentCount: 0,
      serverAnswered: false,
      folderCount: 1,
      tiers: { ses_a: 'normal', ses_b: 'projects/Platform', ses_c: null, ses_d: null },
    })
  })

  it('says what the screen knows besides the tabs, and what caused the report', () => {
    const sessions = [{ id: 'ses_a', child: true, parent_id: 'ses_b' }, { id: 'ses_b' }]
    expect(treeReport({ build: 'abc123', sessions, rows: [], agentCount: 2, serverAnswered: true, trigger: 'foreground' })).toMatchObject({
      trigger: 'foreground', childCount: 1, agentCount: 2, serverAnswered: true,
    })
  })
})
