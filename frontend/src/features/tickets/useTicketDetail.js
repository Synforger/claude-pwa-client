// 開いている票を `GET /tickets/{id}/answer` で読み、 票が変わるたびに読み直す hook (= 画面に写しを持つだけで、 真値は backend)。
// 読み直しの合図は、 `tickets` channel のその票の行が変わること (= 追記・状態・持つ票・届く途中の答えのどれでも変わる)。

import { useEffect, useState } from 'react'
import { fetchTicket } from './ticketApi.js'

/** → { detail, error, reload }。 `detail` はまだ読んでいなければ null、 `error` は読めなかった時の TicketApiError。 */
export function useTicketDetail(id, summary) {
  const [detail, setDetail] = useState(null)
  const [error, setError] = useState(null)
  const [reloadKey, setReloadKey] = useState(0)

  // 別の票へ移ったら、 前の票の中身を持ち越さない
  useEffect(() => {
    setDetail(null)
    setError(null)
  }, [id])

  const sign = summary
    ? [summary.last_at, summary.status, summary.holder, (summary.answer_pending || []).join(',')].join('|')
    : ''
  useEffect(() => {
    if (!id) return undefined
    const controller = new AbortController()
    fetchTicket(id, controller.signal)
      .then((data) => { setDetail(data); setError(null) })
      .catch((e) => { if (e?.name !== 'AbortError') setError(e) })
    return () => controller.abort()
  }, [id, sign, reloadKey])

  return { detail, error, reload: () => setReloadKey((key) => key + 1) }
}
