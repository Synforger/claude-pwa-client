// 設定の画面が backend に頼む 3 つの口 (= settingsApi.js)。 apiFetch を差し替えて、 何を送ったかと失敗の返し方を見る。
import { describe, it, expect, vi, beforeEach } from 'vitest'

const apiFetch = vi.hoisted(() => vi.fn())
vi.mock('../../../src/_common/api.js', () => ({ apiFetch }))

import { continueAccount, fetchSettings, updateSettings } from '../../../src/features/settings/settingsApi.js'

const answer = (status, body) => new Response(JSON.stringify(body), { status })

beforeEach(() => apiFetch.mockReset())

describe('fetchSettings', () => {
  it('returns the view, and throws when the backend does not answer well', async () => {
    apiFetch.mockResolvedValueOnce(answer(200, { accounts: [] }))
    expect(await fetchSettings()).toEqual({ accounts: [] })
    expect(apiFetch).toHaveBeenCalledWith('/settings', undefined)
    apiFetch.mockResolvedValueOnce(answer(500, {}))
    await expect(fetchSettings()).rejects.toThrow('HTTP 500')
  })
})

describe('updateSettings', () => {
  it('puts the patch as JSON and returns the new view', async () => {
    apiFetch.mockResolvedValueOnce(answer(200, { child_sessions_max: 3 }))
    const result = await updateSettings({ child_sessions_max: 3 })
    const [path, options] = apiFetch.mock.calls[0]
    expect([path, options.method, options.headers['Content-Type'], JSON.parse(options.body)])
      .toEqual(['/settings', 'PUT', 'application/json', { child_sessions_max: 3 }])
    expect(result).toEqual({ ok: true, view: { child_sessions_max: 3 } })
  })

  it('returns the reasons of a refused update', async () => {
    apiFetch.mockResolvedValueOnce(answer(400, { detail: { code: 'settings_rejected', params: { reasons: ['x: must be …'] } } }))
    expect(await updateSettings({ x: 1 })).toEqual({ ok: false, status: 400, reasons: ['x: must be …'] })
  })

  it('survives an answer that is not JSON', async () => {
    apiFetch.mockResolvedValueOnce(new Response('oops', { status: 502 }))
    expect(await updateSettings({ x: 1 })).toEqual({ ok: false, status: 502, reasons: [] })
  })
})

describe('continueAccount', () => {
  it('posts to the account and returns who was continued', async () => {
    apiFetch.mockResolvedValueOnce(answer(200, { continued: ['a'], failed: ['b'] }))
    expect(await continueAccount('personal')).toEqual({ ok: true, continued: ['a'], failed: ['b'] })
    expect(apiFetch).toHaveBeenCalledWith('/accounts/personal/continue', { method: 'POST' })
  })

  it('returns the line when the usage is still at it (409)', async () => {
    apiFetch.mockResolvedValueOnce(answer(409, { detail: { code: 'still_at_line', message: '…', params: { line_pct: 70 } } }))
    expect(await continueAccount('personal')).toMatchObject({ ok: false, status: 409, linePct: 70 })
  })

  it('escapes the account id in the path', async () => {
    apiFetch.mockResolvedValueOnce(answer(404, { detail: 'x' }))
    await continueAccount('a b/c')
    expect(apiFetch.mock.calls[0][0]).toBe('/accounts/a%20b%2Fc/continue')
  })
})
