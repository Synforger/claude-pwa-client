// @vitest-environment jsdom
//
// The permission window's dialog: the tool and its input in full, the guard's rewrite beside the original, "k / N"
// only for a queue, "Allow" / "Deny" sending the window's number, and how each way an answer can end is shown.
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, cleanup, fireEvent, waitFor } from '@testing-library/react'

const apiFetch = vi.fn()
vi.mock('../../../src/_common/api.js', () => ({ apiFetch: (...a) => apiFetch(...a) }))

import PermissionWindowDialog from '../../../src/features/permission-window/PermissionWindowDialog.jsx'

const LONG_COMMAND = `echo ${'y'.repeat(1500)}`
const PENDING = {
  number: 4, tool_use_id: 'toolu_1', tool_name: 'Bash', input: { command: LONG_COMMAND }, record_input: null,
  index: 1, count: 1, opened_at: 1700000000,
}

const reply = (status, body) => Promise.resolve({ ok: status < 300, status, json: () => Promise.resolve(body) })
const answerButton = (view, answer) => view.container.querySelector(`[data-cpc-answer="${answer}"]`)

let onClose
beforeEach(() => {
  apiFetch.mockReset()
  onClose = vi.fn()
})
afterEach(cleanup)

const show = (pending = PENDING) => render(<PermissionWindowDialog sid="ses_a" pending={pending} onClose={onClose} />)

describe('PermissionWindowDialog: what it shows', () => {
  it('prints the whole command in a monospace block, never cut', () => {
    const view = show()
    const block = view.container.querySelector('[data-testid="permission-window-running"] pre')
    expect(block.textContent).toBe(LONG_COMMAND)
    expect(view.getByTestId('permission-window-tool').textContent).toBe('Bash')
    expect(view.queryByTestId('permission-window-rewritten')).toBeNull()
    expect(view.queryByTestId('permission-window-original')).toBeNull()
  })

  it('shows both inputs and one line saying the guard rewrote it, when the record differs', () => {
    const view = show({ ...PENDING, input: { command: 'ls' }, record_input: { command: 'rm -rf build' } })
    expect(view.getByTestId('permission-window-rewritten').textContent).not.toBe('')
    expect(view.getByTestId('permission-window-running').textContent).toContain('ls')
    expect(view.getByTestId('permission-window-original').textContent).toContain('rm -rf build')
  })

  it('shows "k / N" for a queue and nothing for a single window', () => {
    const queued = show({ ...PENDING, index: 2, count: 3 })
    expect(queued.getByTestId('permission-window-position').textContent).toBe('2 / 3')
    cleanup()
    const single = show()
    expect(single.queryByTestId('permission-window-position')).toBeNull()
  })

  it('draws nothing without a window', () => {
    const view = show(null)
    expect(view.container.firstChild).toBeNull()
  })

  it('closes by the backdrop and by ×, not by a tap inside the dialog', () => {
    const view = show()
    fireEvent.click(view.container.querySelector('.permission-window-dialog'))
    expect(onClose).not.toHaveBeenCalled()
    fireEvent.click(view.getByTestId('permission-window-dialog'))
    expect(onClose).toHaveBeenCalledTimes(1)
    fireEvent.click(view.container.querySelector('.permission-window-close'))
    expect(onClose).toHaveBeenCalledTimes(2)
  })
})

describe('PermissionWindowDialog: answering', () => {
  it('sends the window\'s number with allow, then closes', async () => {
    apiFetch.mockReturnValue(reply(200, { ok: true }))
    const view = show()
    fireEvent.click(answerButton(view, 'allow'))
    await waitFor(() => expect(onClose).toHaveBeenCalled())
    const [path, options] = apiFetch.mock.calls[0]
    expect(path).toBe('/sessions/ses_a/permission/answer')
    expect(JSON.parse(options.body)).toEqual({ number: 4, answer: 'allow' })
  })

  it('sends deny the same way', async () => {
    apiFetch.mockReturnValue(reply(200, { ok: true }))
    const view = show()
    fireEvent.click(answerButton(view, 'deny'))
    await waitFor(() => expect(onClose).toHaveBeenCalled())
    expect(JSON.parse(apiFetch.mock.calls[0][1].body)).toEqual({ number: 4, answer: 'deny' })
  })

  it('takes one answer at a time: both buttons wait while one is on its way', async () => {
    let finish
    apiFetch.mockReturnValue(new Promise(resolve => { finish = () => resolve({ ok: true, status: 200, json: () => Promise.resolve({ ok: true }) }) }))
    const view = show()
    fireEvent.click(answerButton(view, 'allow'))
    await waitFor(() => expect(answerButton(view, 'deny').disabled).toBe(true))
    fireEvent.click(answerButton(view, 'deny'))
    expect(apiFetch).toHaveBeenCalledTimes(1)
    finish()
    await waitFor(() => expect(onClose).toHaveBeenCalled())
  })

  it('closes quietly when the window was already gone, as the plan approval does', async () => {
    apiFetch.mockReturnValue(reply(200, { ok: false, reason: 'closed' }))
    const view = show()
    fireEvent.click(answerButton(view, 'allow'))
    await waitFor(() => expect(onClose).toHaveBeenCalled())
    expect(view.queryByTestId('permission-window-failed')).toBeNull()
  })

  it('closes quietly on a stale number: the newer window keeps the topbar button', async () => {
    apiFetch.mockReturnValue(reply(409, { detail: { code: 'permission_stale' } }))
    const view = show()
    fireEvent.click(answerButton(view, 'deny'))
    await waitFor(() => expect(onClose).toHaveBeenCalled())
    expect(view.queryByTestId('permission-window-failed')).toBeNull()
  })

  it('stays open with one line and live buttons when nothing is known to have been typed', async () => {
    apiFetch.mockRejectedValue(new Error('network'))
    const view = show()
    fireEvent.click(answerButton(view, 'allow'))
    await waitFor(() => expect(view.getByTestId('permission-window-failed').textContent).not.toBe(''))
    expect(onClose).not.toHaveBeenCalled()
    expect(answerButton(view, 'allow').disabled).toBe(false)
    expect(answerButton(view, 'deny').disabled).toBe(false)
  })

  it('starts clean when a newer window replaces the one on screen', async () => {
    apiFetch.mockRejectedValue(new Error('network'))
    const view = show()
    fireEvent.click(answerButton(view, 'allow'))
    await waitFor(() => expect(view.getByTestId('permission-window-failed')).not.toBeNull())
    view.rerender(<PermissionWindowDialog sid="ses_a" pending={{ ...PENDING, number: 5 }} onClose={onClose} />)
    await waitFor(() => expect(view.queryByTestId('permission-window-failed')).toBeNull())
  })
})
