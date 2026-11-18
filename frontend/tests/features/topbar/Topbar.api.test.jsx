// @vitest-environment jsdom
//
// The top bar of an API tab (no Claude Code behind it): no notes, no sub-agents, no plan approval. A Claude tab's bar
// keeps them.
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, cleanup } from '@testing-library/react'

const mockStatus = vi.fn()
vi.mock('../../../src/features/status-bar/useStatus.js', () => ({ useStatus: (...a) => mockStatus(...a) }))
vi.mock('../../../src/features/screenshare/useMoonlightAvailable.js', () => ({ useMoonlightAvailable: () => false }))
vi.mock('../../../src/features/extensions/ExtensionMenu.jsx', () => ({ default: () => null }))

import Topbar from '../../../src/features/topbar/Topbar.jsx'
import { setSessions, setActiveId } from '../../../src/state/sessions.js'

const CLAUDE = { id: 'ses_claude', agent_id: 'agent_a', title: 'Desk', created_at: 2 }
const API = { id: 'api_support-bot', agent_id: 'agent_a', title: 'Support bot', created_at: 0, kind: 'api' }

beforeEach(() => {
  setSessions([CLAUDE, API])
  mockStatus.mockReturnValue({ pending_plan: { plan: 'x' } })
})
afterEach(() => {
  cleanup()
  setSessions([])
  mockStatus.mockReset()
})

describe('Topbar', () => {
  it('shows the notes, sub-agents and plan-approval buttons of a Claude tab', () => {
    setActiveId('ses_claude')
    const { queryByTestId } = render(<Topbar />)
    expect(queryByTestId('notes-open-button')).not.toBeNull()
    expect(queryByTestId('subagents-open-button')).not.toBeNull()
    expect(queryByTestId('plan-approval-open-button')).not.toBeNull()
  })

  it('shows none of them for an API tab, and still its name', () => {
    setActiveId('api_support-bot')
    const { queryByTestId, container } = render(<Topbar />)
    expect(queryByTestId('notes-open-button')).toBeNull()
    expect(queryByTestId('subagents-open-button')).toBeNull()
    expect(queryByTestId('plan-approval-open-button')).toBeNull()
    expect(container.querySelector('.topbar-title').textContent).toBe('Support bot')
  })
})
