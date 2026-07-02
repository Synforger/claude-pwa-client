// backend HTTPException(detail=dict{code, message, params}) → localized string に変換する helper。
// backend/errors.py の `raise_error` と対。 旧 detail (= plain string) が来ても壊れないよう
// polymorphic に扱う (= 移行過程 / third-party endpoint への防御)。
//
// 使用: import して apiFetch エラー時の detail に通す。
//   const detail = translateHttpErrorDetail((await r.json())?.detail)
//   alert(t('alert.attach_failed', { detail }))
import { tRaw } from '../i18n/t.js'

/**
 * @param {unknown} raw - backend レスポンスの `.detail`。
 *   期待形: `{code: string, message?: string, params?: object}`
 *   互換: `string` (= 旧仕様) or 不明なら fallback を返す
 * @param {string} [fallback] - detail 解決不可時に返すデフォルト
 * @returns {string}
 */
export function translateHttpErrorDetail(raw, fallback = '') {
  if (raw == null) return fallback
  if (typeof raw === 'string') return raw
  if (typeof raw !== 'object') return fallback
  const { code, message, params } = raw
  if (typeof code === 'string' && code) {
    const key = `backend.${code}`
    const translated = tRaw(key, params || {})
    // key が i18n dict に無いと tRaw は key 自体を返す仕様。 backend.<code> がそのまま
    // 返ってきたら翻訳 miss、 message フォールバックに倒す。
    if (translated !== key) return translated
  }
  if (typeof message === 'string' && message) return message
  return fallback
}
