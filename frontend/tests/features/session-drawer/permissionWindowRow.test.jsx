// @vitest-environment jsdom
//
// A tab whose permission window is open shows 🔐 on its row in the list, and no other row does.
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, cleanup, waitFor } from '@testing-library/react'

vi.mock('../../../src/_common/api.js', () => ({
  apiFetch: (path) => Promise.resolve({
    ok: true,
    json: () => Promise.resolve(path === '/accounts' ? [{ id: 'personal', display_name: 'Personal', is_default: true }] : []),
  }),
}))
let mockOpenSids = new Set()
vi.mock('../../../src/features/permission-window/useOpenPermissionWindows.js', () => ({
  useOpenPermissionWindows: () => mockOpenSids,
}))

import SessionDrawer from '../../../src/features/session-drawer/SessionDrawer.jsx'
import { setSessions, setActiveId } from '../../../src/state/sessions.js'
import { setOverlay } from '../../../src/state/ui.js'

const DESK = { id: 'ses_desk', agent_id: 'agent_a', title: 'Desk', created_at: 2, account_id: 'personal' }
const OTHER = { id: 'ses_other', agent_id: 'agent_a', title: 'Other', created_at: 1, account_id: 'personal' }
const API = { id: 'api_support-bot', agent_id: 'agent_a', title: 'Support bot', created_at: 0, kind: 'api', account_id: 'api' }

beforeEach(() => {
  setSessions([DESK, OTHER, API])
  setActiveId('ses_desk')
  setOverlay('drawer', true)
})
afterEach(() => {
  cleanup()
  setSessions([])
  mockOpenSids = new Set()
})

const rowOf = (container, sid) => container.querySelector(`[data-cpc-sid="${sid}"]`)
const markOf = (container, sid) => rowOf(container, sid).querySelector('[data-testid="session-permission-window"]')

describe('the 🔐 on a row of the list', () => {
  it('marks the tabs whose window is open and no others', async () => {
    mockOpenSids = new Set(['ses_other'])
    const { container } = render(<SessionDrawer />)
    await waitFor(() => expect(rowOf(container, 'ses_other')).not.toBeNull())
    expect(markOf(container, 'ses_other').textContent).toBe('🔐')
    expect(markOf(container, 'ses_desk')).toBeNull()
  })

  it('marks nothing while no window is open', async () => {
    const { container } = render(<SessionDrawer />)
    await waitFor(() => expect(rowOf(container, 'ses_other')).not.toBeNull())
    expect(container.querySelector('[data-testid="session-permission-window"]')).toBeNull()
  })

  it('never marks an API tab, which has no Claude Code window', async () => {
    mockOpenSids = new Set(['api_support-bot'])
    const { container } = render(<SessionDrawer />)
    await waitFor(() => expect(rowOf(container, 'api_support-bot')).not.toBeNull())
    expect(markOf(container, 'api_support-bot')).toBeNull()
  })
})
