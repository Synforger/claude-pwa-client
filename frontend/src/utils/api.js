import { API_BASE } from '../constants.js'

// backend URL 組み立ての単一の seam。 各所に直書きされていた `${API_BASE}/...` を
// ここに集約し、 base URL / 共通ヘッダ等を将来 1 箇所で変えられるようにする。

// 文字列の URL を返す (= EventSource など fetch 以外で URL だけ欲しい時)。
export function apiUrl(path) {
  return `${API_BASE}${path}`
}

// 既定 timeout (= backend が完全無応答な時に loading を解放するため)。
// 10s は overview / sessions list 等の通常 GET に十分かつ、 UX 上「もうダメ」 と
// 判定して再操作できる短さの妥協点。 個別呼出しで上書き可能。
const DEFAULT_TIMEOUT_MS = 10_000

// 単発 retry 既定 (= 1 度だけ再試行)。 backend 再起動直後の最初の 1 リクエストが
// connection refused になるケースを吸収する。 retry は GET と HEAD 等 idempotent
// 動詞のみ自動適用、 POST / PATCH / DELETE は明示指定がない限り retry しない。
const IDEMPOTENT_METHODS = new Set(['GET', 'HEAD'])

function isIdempotent(method) {
  if (!method) return true // 既定 GET 扱い
  return IDEMPOTENT_METHODS.has(String(method).toUpperCase())
}

/**
 * fetch の薄いラッパ。 既定で:
 *   - AbortSignal + 10s timeout (= 永遠 pending 防止)
 *   - idempotent な動詞は 1 回だけ自動 retry (= backend 再起動直後の race 吸収)
 *
 * options:
 *   - timeoutMs: number (= 既定 10_000、 false 指定で timeout 無効、 SSE / WS には使わない)
 *   - retry: number (= 既定 idempotent なら 1、 それ以外 0)。 明示指定で上書き
 *   - signal: 外部 AbortSignal (= 渡された場合は内部 timeout と合成)
 *   - その他は fetch にそのまま forward
 *
 * 第 1 引数は backend からの絶対パス (= 先頭 '/')。
 */
export async function apiFetch(path, options = {}) {
  const {
    timeoutMs = DEFAULT_TIMEOUT_MS,
    retry,
    signal: externalSignal,
    ...rest
  } = options
  const url = `${API_BASE}${path}`
  const retryCount = typeof retry === 'number'
    ? retry
    : (isIdempotent(rest.method) ? 1 : 0)

  let lastErr
  for (let attempt = 0; attempt <= retryCount; attempt++) {
    const ctrl = (typeof AbortController !== 'undefined') ? new AbortController() : null
    let timer = null
    let abortFromExternal = null
    if (ctrl) {
      if (timeoutMs && timeoutMs > 0) {
        timer = setTimeout(() => { try { ctrl.abort() } catch { /* ignore */ } }, timeoutMs)
      }
      if (externalSignal) {
        if (externalSignal.aborted) {
          try { ctrl.abort() } catch { /* ignore */ }
        } else {
          abortFromExternal = () => { try { ctrl.abort() } catch { /* ignore */ } }
          externalSignal.addEventListener('abort', abortFromExternal, { once: true })
        }
      }
    }
    try {
      const res = await fetch(url, { ...rest, signal: ctrl?.signal })
      return res
    } catch (e) {
      lastErr = e
      // 外部 signal が abort されたものは retry しない (= 呼出側都合の cancel)
      if (externalSignal && externalSignal.aborted) throw e
      if (attempt >= retryCount) throw e
      // 次の試行へ
    } finally {
      if (timer) clearTimeout(timer)
      if (abortFromExternal && externalSignal) {
        try { externalSignal.removeEventListener('abort', abortFromExternal) } catch { /* ignore */ }
      }
    }
  }
  throw lastErr
}
