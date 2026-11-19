// 票の画面が backend に打つ 4 つの口 (= 全部、 番人がタブに塞いでいる `/tickets/*/answer*` の下)。 失敗は
// `TicketApiError` (= backend の code と、 利用者に出す文) にして投げる。

import { apiFetch } from '../../_common/api.js'
import { translateHttpErrorDetail } from '../../_common/httpError.js'

export class TicketApiError extends Error {
  constructor(code, message, status) {
    super(message || code)
    this.code = code
    this.status = status
  }
}

async function call(path, options = {}) {
  let response
  try {
    response = await apiFetch(path, options)
  } catch (error) {
    if (error?.name === 'AbortError') throw error
    throw new TicketApiError('network', '', 0)
  }
  const body = await response.json().catch(() => null)
  if (!response.ok) {
    const detail = body?.detail
    const code = detail && typeof detail === 'object' && typeof detail.code === 'string' ? detail.code : `http_${response.status}`
    throw new TicketApiError(code, translateHttpErrorDetail(detail, `HTTP ${response.status}`), response.status)
  }
  return body
}

const json = (body) => ({
  method: 'POST',
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify(body),
})
const base = (id) => `/tickets/${encodeURIComponent(id)}/answer`

/** 票を全部読む (= 判定なし。 操作者は全部読める)。 */
export const fetchTicket = (id, signal) => call(base(id), { signal })

/** 見ていた問い (`askedAt`) に、 文か推奨で答える。 */
export const postAnswer = (id, askedAt, { text, recommend }) =>
  call(base(id), json(recommend ? { asked_at: askedAt, recommend: true } : { asked_at: askedAt, text }))

/** 持つタブが無い票を、 `to` のタブへ渡す。 */
export const postHolder = (id, to) => call(`${base(id)}/holder`, json({ to }))

/** 届かなかった答えを確かめた印を付ける。 */
export const postSeen = (id) => call(`${base(id)}/seen`, { method: 'POST' })
