// HttpClient の実装。 frontend で唯一 `fetch(...)` を直接呼ぶ場所 (= Phase 6 lint で強制)。
//
// 既存 utils/api.js の挙動 (= 10s timeout + idempotent auto-retry + signal 合成) を踏襲しつつ、
// ADR-012 traceparent / X-Correlation-Id 付与を実装。 全 response の status を corr_id でひもづけて
// listRecentCorrIds() に流す (= debug inspector が叩く)。

import type { HttpClient, ApiFetchOptions } from '../ports/HttpClient.ts'
import { API_BASE } from '../constants.js'
import { newCorrId, newTraceparent, traceparentFromCorrId, registerCorr, listRecent } from './correlation.ts'

const DEFAULT_TIMEOUT_MS = 10_000
const IDEMPOTENT_METHODS = new Set(['GET', 'HEAD'])

function isIdempotent(method?: string): boolean {
  if (!method) return true
  return IDEMPOTENT_METHODS.has(method.toUpperCase())
}

function mergeSignals(signals: AbortSignal[]): AbortSignal {
  // AbortSignal.any が無い browser (= iOS 16 以下) への shim。 polyfill 風に手動合成。
  const anyApi = (AbortSignal as unknown as { any?: (signals: AbortSignal[]) => AbortSignal }).any
  if (typeof anyApi === 'function') return anyApi(signals)
  const ctrl = new AbortController()
  for (const s of signals) {
    if (s.aborted) { ctrl.abort(); return ctrl.signal }
    s.addEventListener('abort', () => ctrl.abort(), { once: true })
  }
  return ctrl.signal
}

class HttpClientImpl implements HttpClient {
  async apiFetch(path: string, opts: ApiFetchOptions = {}): Promise<Response> {
    const method = opts.method
    const corrId = opts.corrId || newCorrId()
    const traceparent = opts.corrId ? traceparentFromCorrId(opts.corrId) : newTraceparent()
    const headers: Record<string, string> = {
      ...(opts.headers || {}),
      'traceparent': traceparent,
      'x-correlation-id': corrId,
    }
    let body: BodyInit | null | undefined = opts.body
    if (opts.jsonBody !== undefined) {
      headers['content-type'] = headers['content-type'] || 'application/json'
      body = JSON.stringify(opts.jsonBody)
    }

    const timeoutMs = opts.timeout ?? DEFAULT_TIMEOUT_MS
    const retryCount = isIdempotent(method) ? 1 : 0
    const url = `${API_BASE}${path}`

    let lastErr: unknown
    for (let attempt = 0; attempt <= retryCount; attempt++) {
      const timeoutCtrl = new AbortController()
      const timer = timeoutMs > 0
        ? setTimeout(() => { try { timeoutCtrl.abort() } catch { /* ignore */ } }, timeoutMs)
        : null
      const signal = opts.signal
        ? mergeSignals([opts.signal, timeoutCtrl.signal])
        : timeoutCtrl.signal
      try {
        const res = await fetch(url, { method, headers, body, signal })
        registerCorr(corrId, { path, status: res.status })
        return res
      } catch (e) {
        lastErr = e
        if (opts.signal?.aborted) throw e
        if (attempt >= retryCount) throw e
      } finally {
        if (timer !== null) clearTimeout(timer)
      }
    }
    throw lastErr
  }

  listRecentCorrIds() {
    return listRecent()
  }
}

export const httpClient: HttpClient = new HttpClientImpl()

/** 既存 JS コードから呼びやすいよう関数 export も用意 (= W2 で utils/api.js を本関数経由に書き換える)。 */
export function apiFetch(path: string, opts?: ApiFetchOptions): Promise<Response> {
  return httpClient.apiFetch(path, opts)
}
