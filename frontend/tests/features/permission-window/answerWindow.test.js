// How an answer reaches the backend and what each reply of the door means.
import { describe, it, expect, vi, beforeEach } from 'vitest'

const apiFetch = vi.fn()
vi.mock('../../../src/_common/api.js', () => ({ apiFetch: (...a) => apiFetch(...a) }))

import { answerWindow } from '../../../src/features/permission-window/answerWindow.js'

const reply = (status, body) => Promise.resolve({
  ok: status >= 200 && status < 300,
  status,
  json: () => (body === undefined ? Promise.reject(new Error('no body')) : Promise.resolve(body)),
})

beforeEach(() => apiFetch.mockReset())

describe('answerWindow', () => {
  it('posts the window\'s number and the answer to the tab\'s own door', async () => {
    apiFetch.mockReturnValue(reply(200, { ok: true }))
    await answerWindow('ses_a/b', 7, 'allow')
    const [path, options] = apiFetch.mock.calls[0]
    expect(path).toBe('/pty/ses_a%2Fb/permission/answer')
    expect(options.method).toBe('POST')
    expect(JSON.parse(options.body)).toEqual({ number: 7, answer: 'allow' })
  })

  it('says sent when the backend typed the answer', async () => {
    apiFetch.mockReturnValue(reply(200, { ok: true }))
    expect(await answerWindow('ses_a', 1, 'deny')).toBe('sent')
  })

  it('says closed when the window is already gone', async () => {
    apiFetch.mockReturnValue(reply(200, { ok: false, reason: 'closed' }))
    expect(await answerWindow('ses_a', 1, 'allow')).toBe('closed')
  })

  it('tells a window that does not match what was shown', async () => {
    apiFetch.mockReturnValue(reply(200, { ok: false, reason: 'mismatch' }))
    expect(await answerWindow('ses_a', 1, 'allow')).toBe('mismatch')
  })

  it('says stale on a 409, whatever its body', async () => {
    apiFetch.mockReturnValue(reply(409, { detail: { code: 'permission_stale' } }))
    expect(await answerWindow('ses_a', 1, 'allow')).toBe('stale')
    apiFetch.mockReturnValue(reply(409))
    expect(await answerWindow('ses_a', 1, 'allow')).toBe('stale')
  })

  it('says failed when nothing answered, or the answer is an error or not the door\'s', async () => {
    apiFetch.mockRejectedValue(new Error('network'))
    expect(await answerWindow('ses_a', 1, 'allow')).toBe('failed')
    apiFetch.mockReturnValue(reply(500, { detail: 'boom' }))
    expect(await answerWindow('ses_a', 1, 'allow')).toBe('failed')
    apiFetch.mockReturnValue(reply(200))
    expect(await answerWindow('ses_a', 1, 'allow')).toBe('failed')
    apiFetch.mockReturnValue(reply(200, { ok: false, reason: 'something else' }))
    expect(await answerWindow('ses_a', 1, 'allow')).toBe('failed')
  })
})
