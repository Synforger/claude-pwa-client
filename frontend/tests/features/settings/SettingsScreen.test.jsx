// @vitest-environment jsdom
//
// 設定の画面全体: 開くと backend から読み、 section が並び、 眠りの分数を変えて保存できる。 backend には繋がずに fetch を差し替える。
import { describe, it, expect, afterEach, beforeEach, vi } from 'vitest'
import { render, cleanup, fireEvent, waitFor, screen } from '@testing-library/react'
import SettingsScreen from '../../../src/features/settings/SettingsScreen.jsx'
import { setOverlay, getSnapshot as uiSnapshot } from '../../../src/state/ui.js'
import { setLang } from '../../../src/state/locale.js'
import { VIEW } from './fixtures.js'

const json = (body, status = 200) => new Response(JSON.stringify(body), { status })

let calls
function backend(handlers) {
  calls = []
  vi.spyOn(globalThis, 'fetch').mockImplementation(async (url, options = {}) => {
    const path = new URL(String(url), 'http://localhost').pathname
    const method = options.method || 'GET'
    calls.push({ path, method, body: options.body ? JSON.parse(options.body) : null })
    const handler = handlers[`${method} ${path}`]
    return handler ? handler(options) : json({}, 404)
  })
}

beforeEach(() => {
  setLang('ja')
  backend({
    'GET /settings': () => json(VIEW),
    'GET /backend/restartable': () => json({ restartable: true, started_at: 1 }),
  })
})

afterEach(() => {
  setOverlay('settings', false)
  cleanup()
  vi.restoreAllMocks()
})

describe('the screen', () => {
  it('reads the settings when it opens and shows the four sections', async () => {
    render(<SettingsScreen />)
    await screen.findByTestId('settings-accounts')
    for (const id of ['settings-accounts', 'settings-agents', 'settings-notification', 'settings-machine']) {
      expect(screen.getByTestId(id)).not.toBeNull()
    }
    expect(screen.getByTestId('settings-account-work')).not.toBeNull()
    expect(screen.getByTestId('settings-account-personal')).not.toBeNull()
    expect(calls.filter(c => c.path === '/settings').length).toBe(1)
  })

  it('shows, in the machine section, the running version and the start time, and the stall record as none', async () => {
    render(<SettingsScreen />)
    await screen.findByTestId('settings-machine')
    expect(screen.getByTestId('settings-version').textContent).toBe('1.11.1')
    expect(screen.getByTestId('settings-started-at').textContent).not.toBe('—')
    expect(screen.getByTestId('settings-stall').textContent).toBe('無し')
  })

  it('shows the last stall when there is one', async () => {
    backend({
      'GET /settings': () => json({ ...VIEW, machine: { ...VIEW.machine, loop_stall: { stood_still_sec: 31, back_at: '2026-11-09T11:30:00' } } }),
      'GET /backend/restartable': () => json({ restartable: false }),
    })
    render(<SettingsScreen />)
    await screen.findByTestId('settings-stall')
    expect(screen.getByTestId('settings-stall').textContent).toBe('2026-11-09 11:30:00 に戻った (31 秒止まった)')
  })

  it('offers the backend restart only when the backend can be restarted', async () => {
    render(<SettingsScreen />)
    await screen.findByTestId('settings-machine')
    await screen.findByTestId('restart-backend')
    cleanup()
    backend({ 'GET /settings': () => json(VIEW), 'GET /backend/restartable': () => json({ restartable: false }) })
    render(<SettingsScreen />)
    await screen.findByTestId('settings-machine')
    await waitFor(() => expect(calls.some(c => c.path === '/backend/restartable')).toBe(true))
    expect(screen.queryByTestId('restart-backend')).toBeNull()
  })

  it('says when the settings cannot be read', async () => {
    backend({ 'GET /settings': () => json({}, 500) })
    render(<SettingsScreen />)
    expect((await screen.findByRole('alert')).textContent).toContain('設定を読み込めませんでした')
  })

  it('closes with the close button when nothing was changed', async () => {
    setOverlay('settings', true)
    render(<SettingsScreen />)
    await screen.findByTestId('settings-accounts')
    fireEvent.click(screen.getByLabelText(/閉じる|Close/))
    expect(uiSnapshot().overlays.settings).toBe(false)
    expect(screen.queryByText('保存していない変更があります。 捨てて閉じますか?')).toBeNull()
  })

  it('asks before closing with a change that is not saved, and closes only when the operator says to discard it', async () => {
    setOverlay('settings', true)
    render(<SettingsScreen />)
    const limit = await screen.findByTestId('settings-child-limit')
    fireEvent.change(limit.querySelector('[data-testid=settings-child-limit-input]'), { target: { value: '2' } })
    fireEvent.click(screen.getByLabelText(/閉じる|Close/))
    expect(uiSnapshot().overlays.settings).toBe(true)
    await screen.findByText('保存していない変更があります。 捨てて閉じますか?')
    fireEvent.click(screen.getByText('いいえ'))
    expect(uiSnapshot().overlays.settings).toBe(true)
    fireEvent.click(screen.getByLabelText(/閉じる|Close/))
    fireEvent.click(await screen.findByText('はい'))
    expect(uiSnapshot().overlays.settings).toBe(false)
  })

  it('closes without asking once the change is saved', async () => {
    backend({
      'GET /settings': () => json(VIEW),
      'GET /backend/restartable': () => json({ restartable: false }),
      'PUT /settings': () => json({ ...VIEW, child_sessions_max: 2 }),
    })
    setOverlay('settings', true)
    render(<SettingsScreen />)
    const limit = await screen.findByTestId('settings-child-limit')
    fireEvent.change(limit.querySelector('[data-testid=settings-child-limit-input]'), { target: { value: '2' } })
    fireEvent.click(limit.querySelector('[data-testid=settings-child-limit-save]'))
    await waitFor(() => expect(limit.querySelector('.settings-note.ok')).not.toBeNull())
    fireEvent.click(screen.getByLabelText(/閉じる|Close/))
    expect(uiSnapshot().overlays.settings).toBe(false)
  })
})

describe('changing a setting', () => {
  it('saves the sleep minutes of an agent with a PUT of that field only, and shows the answer', async () => {
    backend({
      'GET /settings': () => json(VIEW),
      'GET /backend/restartable': () => json({ restartable: false }),
      'PUT /settings': () => json({ ...VIEW, agents: [{ ...VIEW.agents[0], sleep_minutes: 30 }, VIEW.agents[1]] }),
    })
    render(<SettingsScreen />)
    const card = await screen.findByTestId('settings-agent-agent_a')
    const input = card.querySelector('[data-testid=settings-agent-sleep]')
    fireEvent.change(input, { target: { value: '30' } })
    fireEvent.click(card.querySelector('[data-testid=settings-agent-save]'))
    await waitFor(() => expect(calls.some(c => c.method === 'PUT')).toBe(true))
    expect(calls.find(c => c.method === 'PUT').body).toEqual({ agents: { agent_a: { sleep: { minutes: 30 } } } })
    await waitFor(() => expect(screen.getByTestId('settings-agent-agent_a').querySelector('[data-testid=settings-agent-sleep]').value).toBe('30'))
  })

  it('keeps what is typed in a card when another card saves', async () => {
    backend({
      'GET /settings': () => json(VIEW),
      'GET /backend/restartable': () => json({ restartable: false }),
      'PUT /settings': () => json({ ...VIEW, child_sessions_max: 3 }),
    })
    render(<SettingsScreen />)
    const agent = await screen.findByTestId('settings-agent-agent_a')
    fireEvent.change(agent.querySelector('[data-testid=settings-agent-sleep]'), { target: { value: '45' } })
    const limit = screen.getByTestId('settings-child-limit')
    fireEvent.change(limit.querySelector('[data-testid=settings-child-limit-input]'), { target: { value: '3' } })
    fireEvent.click(limit.querySelector('[data-testid=settings-child-limit-save]'))
    await waitFor(() => expect(calls.some(c => c.method === 'PUT')).toBe(true))
    expect(calls.find(c => c.method === 'PUT').body).toEqual({ child_sessions_max: 3 })
    await waitFor(() => expect(limit.querySelector('.settings-note.ok')).not.toBeNull())
    expect(screen.getByTestId('settings-agent-agent_a').querySelector('[data-testid=settings-agent-sleep]').value).toBe('45')
  })

  it('shows the reasons when the backend refuses', async () => {
    backend({
      'GET /settings': () => json(VIEW),
      'GET /backend/restartable': () => json({ restartable: false }),
      'PUT /settings': () => json({ detail: { code: 'settings_rejected', params: { reasons: ['child_sessions_max: must be …'] } } }, 400),
    })
    render(<SettingsScreen />)
    const limit = await screen.findByTestId('settings-child-limit')
    fireEvent.change(limit.querySelector('[data-testid=settings-child-limit-input]'), { target: { value: '9' } })
    fireEvent.click(limit.querySelector('[data-testid=settings-child-limit-save]'))
    await waitFor(() => expect(limit.querySelector('[role=alert]')).not.toBeNull())
    expect(limit.querySelector('[role=alert]').textContent).toContain('child_sessions_max: must be …')
  })

  it('continues the stopped tabs of an account and reads the settings again', async () => {
    backend({
      'GET /settings': () => json(VIEW),
      'GET /backend/restartable': () => json({ restartable: false }),
      'POST /accounts/personal/continue': () => json({ continued: ['a', 'b'], failed: [] }),
    })
    render(<SettingsScreen />)
    const held = await screen.findByTestId('settings-held')
    fireEvent.click(held.querySelector('[data-testid=settings-continue]'))
    await waitFor(() => expect(calls.some(c => c.method === 'POST' && c.path === '/accounts/personal/continue')).toBe(true))
    await waitFor(() => expect(calls.filter(c => c.path === '/settings' && c.method === 'GET').length).toBe(2))
  })

  it('unpins a tab through the tab setting and reads the settings again', async () => {
    backend({
      'GET /settings': () => json(VIEW),
      'GET /backend/restartable': () => json({ restartable: false }),
      'PATCH /sessions/ses_p': () => json({ ok: true }),
    })
    render(<SettingsScreen />)
    const pinned = await screen.findByTestId('settings-pinned')
    fireEvent.click(pinned.querySelector('[data-testid=settings-unpin]'))
    await waitFor(() => expect(calls.some(c => c.method === 'PATCH' && c.path === '/sessions/ses_p')).toBe(true))
    expect(calls.find(c => c.method === 'PATCH').body).toEqual({ account_pinned: false })
    await waitFor(() => expect(calls.filter(c => c.path === '/settings' && c.method === 'GET').length).toBe(2))
  })
})
