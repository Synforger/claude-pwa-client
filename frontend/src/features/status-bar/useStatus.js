import { useState, useEffect } from 'react'
import { registerConnection, notifyConnectionChange } from '../../hooks/useConnectionStatus.js'
import { sessionsStatusSse } from '../../transport/sse-sessions-status.ts'

// 全 session の status を transport/sse-sessions-status.ts singleton (= ADR-019) で受信し、
// activeSid に対応するエントリを返す。 旧来の new EventSource 直書きは ADR-019 で transport singleton
// に集約済、 ここは subscribe するだけ。
//
// 設計判断 (2026-06-10): 全 sid を 1 接続で配信 (= /sessions/overview/stream と同じパターン)、
// タブ切替で SSE 張り替え不要 → 切替コスト 0。 受信 payload (= {sid1: {...}, sid2: {...}}) から
// 自 activeSid のものを返す。

export function useStatus(activeSession) {
  const [allStatus, setAllStatus] = useState({})

  useEffect(() => {
    let live = false
    const unreg = registerConnection(() => live)
    const unsub = sessionsStatusSse.subscribe(data => {
      live = true
      notifyConnectionChange()
      if (data && typeof data === 'object') setAllStatus(data)
    })
    return () => { unreg(); unsub(); live = false }
  }, [])

  const sid = activeSession?.id
  return sid ? (allStatus[sid] || null) : null
}
