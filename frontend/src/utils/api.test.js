import { describe, it, expect, vi, afterEach } from 'vitest'
import { apiUrl, apiFetch } from './api.js'

// API_BASE は constants.js 由来。 test 環境 (= import.meta.env.PROD=false) では
// 'http://localhost:8765' に解決される。
afterEach(() => vi.restoreAllMocks())

describe('api helpers (apiUrl / apiFetch)', () => {
  it('apiUrl appends the path to the base', () => {
    // test 環境では API_BASE が空文字に解決されることもあるので、 base の具体値ではなく
    // 「base + path」 になっている (= 末尾がパス) ことだけ検証する。
    expect(apiUrl('/sessions')).toMatch(/\/sessions$/)
    expect(apiUrl('/a/b')).toMatch(/\/a\/b$/)
  })

  it('apiFetch calls fetch with the prefixed url and forwards options + injects AbortSignal', async () => {
    const spy = vi.fn(() => Promise.resolve({ ok: true }))
    vi.stubGlobal('fetch', spy)
    await apiFetch('/status/x', { method: 'GET' })
    expect(spy).toHaveBeenCalledTimes(1)
    const [url, opts] = spy.mock.calls[0]
    expect(url).toContain('/status/x')
    expect(opts.method).toBe('GET')
    // 既定で AbortSignal が注入される (= 10s timeout)。
    expect(opts.signal).toBeDefined()
  })

  it('apiFetch retries once for GET on network failure', async () => {
    let calls = 0
    const spy = vi.fn(() => {
      calls++
      if (calls === 1) return Promise.reject(new Error('boom'))
      return Promise.resolve({ ok: true })
    })
    vi.stubGlobal('fetch', spy)
    const res = await apiFetch('/ping')
    expect(res.ok).toBe(true)
    expect(spy).toHaveBeenCalledTimes(2) // 1 fail + 1 retry
  })

  it('apiFetch does not retry POST by default', async () => {
    const spy = vi.fn(() => Promise.reject(new Error('boom')))
    vi.stubGlobal('fetch', spy)
    await expect(apiFetch('/p', { method: 'POST' })).rejects.toThrow('boom')
    expect(spy).toHaveBeenCalledTimes(1) // POST は idempotent でないので retry なし
  })

  it('apiFetch respects retry: false override', async () => {
    const spy = vi.fn(() => Promise.reject(new Error('boom')))
    vi.stubGlobal('fetch', spy)
    await expect(apiFetch('/g', { retry: 0 })).rejects.toThrow('boom')
    expect(spy).toHaveBeenCalledTimes(1)
  })
})
