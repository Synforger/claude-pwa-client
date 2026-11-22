// Send the operator's answer to a permission window: POST /sessions/<id>/permission/answer with the window's number.
// Used by PermissionWindowDialog.jsx.
import { apiFetch } from '../../_common/api.js'

/** What came of an answer.
 *  - `sent`: the backend typed it into the window.
 *  - `closed`: the window was already gone (answered elsewhere, or Claude moved on).
 *  - `stale`: the number is an older window's (409): the answer was not typed, a newer window is open.
 *  - `failed`: no answer from the backend, or an error: nothing is known to have been typed.
 *  @typedef {'sent' | 'closed' | 'stale' | 'failed'} AnswerOutcome */

const STALE_STATUS = 409

/**
 * @param {string} sid the tab's id
 * @param {number} number the window's number (`pending_permission.number`), so a late answer cannot reach a newer window
 * @param {'allow' | 'deny'} answer
 * @returns {Promise<AnswerOutcome>}
 */
export async function answerWindow(sid, number, answer) {
  let res
  try {
    res = await apiFetch(`/sessions/${encodeURIComponent(sid)}/permission/answer`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ number, answer }),
    })
  } catch {
    return 'failed'
  }
  if (res.status === STALE_STATUS) return 'stale'
  if (!res.ok) return 'failed'
  const body = await res.json().catch(() => null)
  if (body?.ok === true) return 'sent'
  return body?.reason === 'closed' ? 'closed' : 'failed'
}
