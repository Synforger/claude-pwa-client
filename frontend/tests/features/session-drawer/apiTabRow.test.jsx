// @vitest-environment jsdom
//
// The row of an API tab in the conversation list (no Claude Code behind it): its name and how much of the context its
// conversation holds, and none of a Claude tab's marks (asleep, account, work, unread) and no ⋯ menu.
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, cleanup, waitFor } from '@testing-library/react'

vi.mock('../../../src/_common/api.js', () => ({
  apiFetch: (path) => Promise.resolve({
    ok: true,
    json: () => Promise.resolve(path === '/accounts'
      ? [{ id: 'personal', display_name: 'Personal', is_default: true }, { id: 'company', display_name: 'Company' }]
      : []),
  }),
}))

import SessionDrawer from '../../../src/features/session-drawer/SessionDrawer.jsx'
import { setSessions, setActiveId, setUnreadDone, getSnapshot } from '../../../src/state/sessions.js'
import { setOverlay } from '../../../src/state/ui.js'

const CLAUDE = { id: 'ses_claude', agent_id: 'agent_a', title: 'Desk', created_at: 2, account_id: 'company', asleep: true }
const API = { id: 'api_support-bot', agent_id: 'agent_a', title: 'Support bot', created_at: 0, kind: 'api',
  account_id: 'api', context_tokens: 12300, asleep: false }

beforeEach(() => {
  setSessions([CLAUDE, API])
  setActiveId('ses_claude')
  setOverlay('drawer', true)
})
afterEach(() => {
  cleanup()
  setSessions([])
  setUnreadDone('api_support-bot', false)
})

const rowOf = (container, sid) => container.querySelector(`[data-cpc-sid="${sid}"]`)

describe('the row of an API tab', () => {
  it('shows its name and its context amount', async () => {
    const { container } = render(<SessionDrawer />)
    await waitFor(() => expect(rowOf(container, 'api_support-bot')).not.toBeNull())
    const row = rowOf(container, 'api_support-bot')
    expect(row.querySelector('.drawer-item-title').textContent).toBe('Support bot')
    expect(row.querySelector('[data-testid="session-context"]').textContent).toBe('12.3k')
  })

  it('shows no sleep, account, badge or menu, however the tab is flagged', async () => {
    setUnreadDone('api_support-bot', true)
    setSessions([CLAUDE, { ...API, asleep: true }])
    const { container } = render(<SessionDrawer />)
    await waitFor(() => expect(rowOf(container, 'api_support-bot')).not.toBeNull())
    const row = rowOf(container, 'api_support-bot')
    expect(row.querySelector('[data-testid="session-asleep"]')).toBeNull()
    expect(row.querySelector('.drawer-item-account')).toBeNull()
    expect(row.querySelector('.tab-badge')).toBeNull()
    expect(row.querySelector('.drawer-item-menu')).toBeNull()
  })

  it('shows no amount while the tab has none (never 0)', async () => {
    setSessions([CLAUDE, { ...API, context_tokens: null }])
    const { container } = render(<SessionDrawer />)
    await waitFor(() => expect(rowOf(container, 'api_support-bot')).not.toBeNull())
    expect(rowOf(container, 'api_support-bot').querySelector('[data-testid="session-context"]')).toBeNull()
  })

  it('leaves a Claude tab\'s row as it was: asleep mark, account label and menu', async () => {
    const { container } = render(<SessionDrawer />)
    await waitFor(() => expect(rowOf(container, 'ses_claude')).not.toBeNull())
    await waitFor(() => expect(rowOf(container, 'ses_claude').querySelector('.drawer-item-account')).not.toBeNull())
    const row = rowOf(container, 'ses_claude')
    expect(row.querySelector('[data-testid="session-asleep"]')).not.toBeNull()
    expect(row.querySelector('.drawer-item-menu')).not.toBeNull()
    expect(row.querySelector('[data-testid="session-context"]')).toBeNull()
  })

  it('does not let the only Claude tab be removed because an API tab is also listed', async () => {
    const { container } = render(<SessionDrawer />)
    await waitFor(() => expect(rowOf(container, 'ses_claude')).not.toBeNull())
    expect(getSnapshot().sessions).toHaveLength(2)
    rowOf(container, 'ses_claude').querySelector('.drawer-item-menu').click()
    await waitFor(() => expect(container.querySelector('.drawer-item-popup .danger')).not.toBeNull())
    expect(container.querySelector('.drawer-item-popup .danger').disabled).toBe(true)
  })
})
