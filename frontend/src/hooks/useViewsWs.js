/**
 * 「今どの session を見ているか」 を backend に realtime で通知する WebSocket。
 *
 * - PWA visible 中だけ /views/ws に常時接続
 * - 接続時 + activeSid 変化時に {sid} を 1 メッセージ送る
 * - PWA バックグラウンドで iOS が socket を切る → backend 即時検知 → 通知が出る
 *   (= 接続が「視認中」 のシグナルそのもの、 stale 概念なし)
 * - 切断 → 3 秒後に再接続 (visible 中のみ)
 *
 * heartbeat は不要 (= 接続生存自体がシグナル)、 ディレイは TCP レベルで最小。
 */
import { useEffect, useRef } from 'react'
import { API_BASE } from '../constants.js'

function toWsUrl(path) {
  const base = API_BASE || window.location.origin
  return base.replace(/^http/, 'ws') + path
}

export function useViewsWs(activeSid) {
  const wsRef = useRef(null)
  const sidRef = useRef(activeSid)
  // sidRef は接続 onopen 時に「最新の activeSid」 を読むためのコピー。 render 中の
  // ref 直書きは React 警告対象なので effect 内で同期する。
  useEffect(() => { sidRef.current = activeSid }, [activeSid])

  useEffect(() => {
    if (typeof window === 'undefined') return
    let cancelled = false
    let reconnectTimer = null

    const connect = () => {
      if (cancelled || document.hidden) return
      const existing = wsRef.current
      if (existing && (existing.readyState === WebSocket.OPEN || existing.readyState === WebSocket.CONNECTING)) {
        return
      }
      let ws
      try {
        ws = new WebSocket(toWsUrl('/views/ws'))
      } catch {
        return
      }
      wsRef.current = ws
      ws.onopen = () => {
        try { ws.send(JSON.stringify({ sid: sidRef.current || null })) } catch { /* ignore */ }
      }
      ws.onclose = () => {
        if (wsRef.current === ws) wsRef.current = null
        if (cancelled || document.hidden) return
        // 短い backoff で再接続 (= visible 中のみ)
        reconnectTimer = setTimeout(connect, 3000)
      }
      ws.onerror = () => { /* onclose も来るので個別処理不要 */ }
    }

    const onVis = () => {
      if (document.hidden) {
        if (reconnectTimer) { clearTimeout(reconnectTimer); reconnectTimer = null }
        const ws = wsRef.current
        if (ws) { try { ws.close() } catch { /* ignore */ } }
      } else {
        connect()
      }
    }

    if (!document.hidden) connect()
    document.addEventListener('visibilitychange', onVis)

    return () => {
      cancelled = true
      document.removeEventListener('visibilitychange', onVis)
      if (reconnectTimer) clearTimeout(reconnectTimer)
      const ws = wsRef.current
      if (ws) { try { ws.close() } catch { /* ignore */ } }
      wsRef.current = null
    }
  }, [])

  // activeSid 変化時に接続中なら即時 update。 切断中は次回 onopen で sidRef から送る。
  useEffect(() => {
    const ws = wsRef.current
    if (ws && ws.readyState === WebSocket.OPEN) {
      try { ws.send(JSON.stringify({ sid: activeSid || null })) } catch { /* ignore */ }
    }
  }, [activeSid])
}
