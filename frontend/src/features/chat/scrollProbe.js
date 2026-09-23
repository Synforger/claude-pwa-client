// 【一時計測】 最下端への張り付きの実機確認用 (= 2026-09-23、 張り付き判定を「上スクロールでだけ外す」
// に直した後、 iPhone で開く / ↓ で途中に止まらなくなったかを backend.log の `sw-log` で確かめる)。
// 確認が済んだら本 file と useAutoScroll からの呼び出しを外す。
import { httpClient } from '../../transport/http.ts'
import { CLIENT_TAG } from '../app-effects/usePerfBeacon.js'

// 開いた / 戻った / ↓ を押した後、 中身の遅れた伸びが収まるのを待ってから位置を測る。
export const SETTLE_CHECK_MS = 1500
const MIN_INTERVAL_MS = 1000
let lastSentAt = 0

function measure(el) {
  return {
    top: Math.round(el.scrollTop),
    height: el.scrollHeight,
    view: el.clientHeight,
    distance: Math.round(el.scrollHeight - el.scrollTop - el.clientHeight),
  }
}

export function reportScroll(stage, el, extra) {
  if (!el) return
  const now = Date.now()
  if (now - lastSentAt < MIN_INTERVAL_MS) return
  lastSentAt = now
  const payload = { stage: `scroll:${stage}`, client: CLIENT_TAG, ...measure(el), ...(extra || {}) }
  httpClient.apiFetch('/log/sw', { method: 'POST', jsonBody: payload }).catch(() => {})
}
