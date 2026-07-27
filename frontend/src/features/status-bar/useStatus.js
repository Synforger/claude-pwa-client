import { useState, useEffect } from 'react'
import { registerConnection, notifyConnectionChange } from '../../transport/connectionStatus.js'
import { getCachedAllStatus } from '../../transport/statusCache.ts'
import { statusSse } from '../../transport/select.ts'

// 全 session の status を unified stream の status channel (= transport/select.ts) で受信し、
// activeSid に対応するエントリを返す。 旧来の new EventSource 直書きは ADR-019 で transport singleton
// に集約済、 ここは subscribe するだけ。
//
// 設計判断 (2026-06-10): 全 sid を 1 接続で配信 (= /sessions/overview/stream と同じパターン)、
// タブ切替で SSE 張り替え不要 → 切替コスト 0。 受信 payload (= {sid1: {...}, sid2: {...}}) から
// 自 activeSid のものを返す。

export function useStatus(activeSession) {
  // 起動瞬間は前回 session の最終 payload で hydrate (= "---" を出さない、 2026-07-13)。
  // live snapshot が届き次第 setAllStatus で上書きされる。 鮮度は offline chip + heartbeat
  // watchdog が担保する (= 古い値を出し続ける事故は接続監視側で殺す)。
  const [allStatus, setAllStatus] = useState(() => getCachedAllStatus())

  useEffect(() => {
    let live = false
    const unreg = registerConnection(() => live)
    const unsub = statusSse.subscribe(data => {
      live = true
      notifyConnectionChange()
      if (data && typeof data === 'object') setAllStatus(data)
    })
    return () => { unreg(); unsub(); live = false }
  }, [])

  const sid = activeSession?.id
  return sid ? (allStatus[sid] || null) : null
}
