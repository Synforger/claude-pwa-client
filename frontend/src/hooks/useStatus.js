import { useState, useEffect, useRef } from 'react'
import { apiUrl } from '../utils/api.js'

// 全 session の status を 1 本の SSE (/sessions/status/stream) で受信し、 activeSid に
// 対応するエントリを返す。
//
// 設計判断 (2026-06-10): 旧設計は sid 毎に /status/{sid}/stream を張り替える形で、 タブ
// 切替のたびに SSE を旧 close + 新接続。 iOS Safari で TCP 確立に 1-3 秒かかり「タブ切替
// したのに status が出るのが遅い」 という体感だった。 全 sid を 1 接続で配信する設計
// (= /sessions/overview/stream と同じパターン) に変えると、 タブ切替で SSE 張り替えが
// 不要 → 切替コスト 0。 各 client は受信 payload (= {sid1: {...}, sid2: {...}}) から
// 自分の activeSid のものを取り出すだけ。
//
// fallback:
//   - SSE 接続失敗時は EventSource が auto-reconnect (= retry 3 秒)
//   - 接続できない間は最後に受信した snapshot が残る

export function useStatus(activeSession) {
  const [allStatus, setAllStatus] = useState({})
  // EventSource を mount 1 回だけ張る (= activeSession 変化で再接続しない)。
  const evtRef = useRef(null)

  useEffect(() => {
    let evt = null
    try {
      evt = new EventSource(apiUrl('/sessions/status/stream'))
      evt.onmessage = (e) => {
        if (!e.data) return
        try {
          const data = JSON.parse(e.data)
          if (data && typeof data === 'object') setAllStatus(data)
        } catch { /* ignore parse error */ }
      }
      evtRef.current = evt
    } catch {
      /* EventSource not supported */
    }
    return () => {
      if (evt) try { evt.close() } catch { /* ignore */ }
      evtRef.current = null
    }
  }, [])

  const sid = activeSession?.id
  return sid ? (allStatus[sid] || null) : null
}
