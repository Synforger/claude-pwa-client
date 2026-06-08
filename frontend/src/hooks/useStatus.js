import { useState, useEffect } from 'react'
import { apiFetch, apiUrl } from '../utils/api.js'

// 現在 active なセッションの status を backend からリアルタイム受信する。
//
// 仕様:
//   - polling 撤廃、 backend が `/status/{sid}/stream` で SSE push する形に統一
//   - backend 側で current_tool / todos / pending_question 等が変化するたびに
//     `status_event.set()` が呼ばれて即時 push される (= ms 単位)
//   - frontend は EventSource で subscribe するだけ、 fetch interval は無し
//
// 設計判断 (2026-06-09): タブ切替時に旧 SSE を overlap close で残す改修を入れていたが、
// 「旧タブの status が新タブにそのまま見え続ける」 不具合を呼んだので撤回。 sid 切替は
// 「別物の status」 なので旧値を引きずるべきでなく、 即 close + setStatus(null) で
// 「読込中」 を明示し、 すぐ初期 fetch + SSE で新値に置き換える。 切替時の数 100ms の
// 空白 (= iOS で 1-3s) はちらつき軽減より「正しい値が出る」 を優先。
//
// fallback:
//   - SSE 接続失敗時は EventSource が auto-reconnect (= retry 3 秒)
//   - 接続できない間は最後に受信した status が残る (= 同一 sid 内に限る)

export function useStatus(activeSession) {
  const [status, setStatus] = useState(null)

  useEffect(() => {
    const sid = activeSession?.id
    if (!sid) { setStatus(null); return }

    // sid 切替時は前タブの status を即捨てる (= 別物なので引きずらない)。
    setStatus(null)

    let cancelled = false
    let sseReceived = false
    let evt = null

    // 接続時に初期値を読みに行く (= EventSource の初回 data 到着前のチラ見せ防止)。
    // SSE 接続後はすぐに status snapshot が push されるので、 ここの fetch は補助。
    // ただし fetch のレスポンスが SSE より遅れて返ると、 古い snapshot で SSE 値を
    // 上書きしてしまう race があった。 sseReceived フラグで「SSE が先に来てたら捨てる」。
    apiFetch(`/status/${sid}`)
      .then(r => r.ok ? r.json() : null)
      .then(d => { if (!cancelled && !sseReceived && d) setStatus(d) })
      .catch(() => {})

    try {
      evt = new EventSource(apiUrl(`/status/${sid}/stream`))
      evt.onmessage = (e) => {
        if (cancelled) return
        sseReceived = true
        try {
          const data = JSON.parse(e.data)
          setStatus(data)
        } catch { /* ignore parse error */ }
      }
    } catch {
      /* EventSource not supported, leave status as initial fetch result */
    }

    return () => {
      cancelled = true
      if (evt) { try { evt.close() } catch { /* ignore */ } }
    }
  }, [activeSession?.id])

  return status
}
