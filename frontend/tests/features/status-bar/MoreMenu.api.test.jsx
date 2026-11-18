// @vitest-environment jsdom
//
// The ⋯ menu holds what only a tab with a Claude Code behind it has (attach, file tree, terminal, reload, end the
// session): an API tab has none of it, so the whole menu is left out.
import { describe, it, expect, beforeEach, afterEach } from 'vitest'
import { render, cleanup } from '@testing-library/react'
import MoreMenu from '../../../src/features/status-bar/MoreMenu.jsx'
import { setSessions, setActiveId } from '../../../src/state/sessions.js'

const CLAUDE = { id: 'ses_claude', agent_id: 'agent_a', title: 'Desk', created_at: 2 }
const API = { id: 'api_support-bot', agent_id: 'agent_a', title: 'Support bot', created_at: 0, kind: 'api' }

beforeEach(() => setSessions([CLAUDE, API]))
afterEach(() => { cleanup(); setSessions([]) })

describe('MoreMenu', () => {
  it('is there for a Claude tab', () => {
    setActiveId('ses_claude')
    const { queryByTestId } = render(<MoreMenu />)
    expect(queryByTestId('more-menu-toggle')).not.toBeNull()
  })

  it('is left out for an API tab', () => {
    setActiveId('api_support-bot')
    const { queryByTestId, container } = render(<MoreMenu />)
    expect(queryByTestId('more-menu-toggle')).toBeNull()
    expect(container.textContent).toBe('')
  })
})
