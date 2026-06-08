import { useState, useEffect, useRef } from 'react'
import { apiFetch, apiUrl } from '../utils/api.js'

// 現在 active なセッションの status を backend からリアルタイム受信する。
//
// 仕様 (2026-05-17 改修):
//   - polling 撤廃、 backend が `/status/{sid}/stream` で SSE push する形に統一
//   - backend 側で current_tool / todos / pending_question 等が変化するたびに
//     `status_event.set()` が呼ばれて即時 push される (= ms 単位)
//   - frontend は EventSource で subscribe するだけ、 fetch interval は無し
//   - 電池消費: 持続 SSE 接続 1 本 (= 接続維持コスト、 idle 時 fetch ゼロ)
//
// fallback:
//   - SSE 接続失敗時は EventSource が auto-reconnect (= retry 3 秒)
//   - 接続できない間は最後に受信した status が残る (= 表示が古くなる可能性あるが
//     visibilitychange 復帰で再接続が走るのでフォアでは数秒で復旧)

// タブ切替で SSE を即 close → 新規開く形式は iOS で TCP 確立に 1-3 秒かかり、 その間
// status が消えて表示が暗転する。 新 SSE が open するまで旧 SSE を活かして滑らかに移行する
// (overlap close pattern)。 高速連続切替で grace timer 内に open しなければ強制 close。
const OVERLAP_GRACE_MS = 5000

export function useStatus(activeSession) {
  const [status, setStatus] = useState(null)
  // 旧 EventSource: 新 SSE の onopen 通知時に close する (= 切替体験の暗転消し)。
  const prevEvtRef = useRef(null)

  useEffect(() => {
    const sid = activeSession?.id
    if (!sid) {
      setStatus(null)
      if (prevEvtRef.current) {
        try { prevEvtRef.current.close() } catch { /* ignore */ }
        prevEvtRef.current = null
      }
      return
    }

    let cancelled = false
    let sseReceived = false
    let evt = null

    // 接続時に初期値を読みに行く (= EventSource の初回 data 到着前のチラ見せ防止)。
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
      evt.onopen = () => {
        // 新 SSE が確立したので、 残ってる旧 SSE があれば close する。
        const prev = prevEvtRef.current
        if (prev && prev !== evt) {
          try { prev.close() } catch { /* ignore */ }
        }
        prevEvtRef.current = evt
      }
    } catch {
      /* EventSource not supported */
    }

    return () => {
      cancelled = true
      // 新 SSE が open するまで旧 (= この evt) を残す。 prevEvtRef に詰めて、 次 effect の
      // onopen で close。 unmount / 高速連続切替で onopen が来ないケースに備えて grace timer。
      if (evt && evt !== prevEvtRef.current) {
        prevEvtRef.current = evt
      }
      const stale = evt
      setTimeout(() => {
        if (stale && prevEvtRef.current === stale) {
          try { stale.close() } catch { /* ignore */ }
          prevEvtRef.current = null
        }
      }, OVERLAP_GRACE_MS)
    }
  }, [activeSession?.id])

  return status
}
