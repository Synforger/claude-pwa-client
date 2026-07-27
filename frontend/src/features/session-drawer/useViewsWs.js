/**
 * 「今どの session を見ているか」 を backend に通知する hook (= unified stream の
 * control op=view / op=stop 経由、 旧 /views/ws WebSocket は 2026-07-27 退役)。
 */
import { useCallback, useEffect } from 'react'
import { viewsChannel } from '../../transport/select.ts'

// 統合 transport 有効時: /views/ws を張らず、 視認申告 + Stop を共有 SSE 接続の
// control POST に委譲する (= 2026-07-14 電力効率工事、 接続 1 本削減)。 接続断 =
// views 登録自動消滅の stale-free 性質は SSE 切断が同じ役割を担う。
function useViewsUnified(activeSid) {
  useEffect(() => {
    viewsChannel.setActiveSid(activeSid || null)
  }, [activeSid])
  const sendStopIntent = useCallback((sid) => {
    if (sid) viewsChannel.sendStopIntent(sid)
  }, [])
  return { sendStopIntent }
}

// 公開 entry (= 2026-07-27 legacy WS 退役、 unified 一本)。
export const useViewsWs = useViewsUnified
