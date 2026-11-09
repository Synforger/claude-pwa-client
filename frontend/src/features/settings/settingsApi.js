// 設定の画面が backend に頼む 3 つの口 (= GET /settings、 PUT /settings、 POST /accounts/{口座}/continue)。
// 失敗は例外にせず { ok: false, status, reasons } で返す (= 画面が欄の下に理由を出す)。
import { apiFetch } from '../../_common/api.js'
import { reasonsOf } from './settingsDraft.js'

async function bodyOf(response) {
  try {
    return await response.json()
  } catch {
    return null
  }
}

/** 設定の画面が出す値を読む。 失敗したら例外。 */
export async function fetchSettings(signal) {
  const response = await apiFetch('/settings', signal ? { signal } : undefined)
  if (!response.ok) throw new Error(`HTTP ${response.status}`)
  return response.json()
}

/** 変える欄だけを送る。 → { ok: true, view } か { ok: false, status, reasons }。 */
export async function updateSettings(patch) {
  const response = await apiFetch('/settings', {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(patch),
  })
  const body = await bodyOf(response)
  if (response.ok) return { ok: true, view: body }
  return { ok: false, status: response.status, reasons: reasonsOf(body) }
}

/** 線で止まっているタブを続ける。 → { ok: true, continued, failed } か { ok: false, status, reasons, linePct }。 */
export async function continueAccount(account) {
  const response = await apiFetch(`/accounts/${encodeURIComponent(account)}/continue`, { method: 'POST' })
  const body = await bodyOf(response)
  if (response.ok) return { ok: true, continued: body.continued, failed: body.failed }
  return { ok: false, status: response.status, reasons: reasonsOf(body), linePct: body?.detail?.params?.line_pct ?? null }
}
