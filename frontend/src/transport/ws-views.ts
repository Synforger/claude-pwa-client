// ViewsTransport 実装。 /views/ws (= activeSid realtime sync)。
// visible 中のみ接続、 heartbeat なし、 3s backoff。 ADR-013。

import type { ViewsTransport } from '../ports/ViewsTransport.ts'
import { API_BASE } from '../constants.js'

const RECONNECT_DELAY_MS = 3_000

function wsBaseFrom(httpBase: string): string {
  if (!httpBase) {
    if (typeof window !== 'undefined' && window.location) {
      const proto = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
      return `${proto}//${window.location.host}`
    }
    return ''
  }
  if (httpBase.startsWith('https:')) return 'wss:' + httpBase.slice(6)
  if (httpBase.startsWith('http:')) return 'ws:' + httpBase.slice(5)
  return httpBase
}

const WS_BASE = wsBaseFrom(API_BASE)

class ViewsTransportImpl implements ViewsTransport {
  private ws: WebSocket | null = null
  private activeSid: string | null = null
  private reconnectTimer: ReturnType<typeof setTimeout> | null = null
  state: 'idle' | 'connecting' | 'open' | 'reconnecting' | 'closed' = 'idle'

  start(): void {
    if (this.ws) return
    if (typeof document !== 'undefined' && document.visibilityState !== 'visible') return
    this.openConn()
  }

  stop(): void {
    this.clearReconnect()
    if (this.ws) {
      try { this.ws.close(1000, 'client-intent') } catch { /* ignore */ }
      this.ws = null
    }
    this.state = 'closed'
  }

  setActiveSid(sid: string | null): void {
    this.activeSid = sid
    if (this.ws?.readyState === WebSocket.OPEN) {
      try { this.ws.send(JSON.stringify({ sid })) } catch (e) { console.warn('[ws-views] setActiveSid send failed', e) }
    }
  }

  sendStopIntent(sid: string): void {
    if (this.ws?.readyState === WebSocket.OPEN) {
      try { this.ws.send(JSON.stringify({ type: 'stop', sid })) } catch (e) { console.warn('[ws-views] stop intent send failed', e) }
    }
  }

  private openConn(): void {
    this.clearReconnect()
    this.state = 'connecting'
    const url = `${WS_BASE}/views/ws`
    this.ws = new WebSocket(url)
    this.ws.onopen = () => {
      this.state = 'open'
      if (this.activeSid !== null) {
        try { this.ws?.send(JSON.stringify({ sid: this.activeSid })) } catch { /* ignore */ }
      }
    }
    this.ws.onclose = () => this.onClose()
    this.ws.onerror = () => { /* onclose で再接続 */ }
  }

  private onClose(): void {
    this.ws = null
    if (typeof document !== 'undefined' && document.visibilityState !== 'visible') {
      this.state = 'closed'
      return
    }
    this.state = 'reconnecting'
    this.reconnectTimer = setTimeout(() => { this.openConn() }, RECONNECT_DELAY_MS)
  }

  private clearReconnect(): void {
    if (this.reconnectTimer) { clearTimeout(this.reconnectTimer); this.reconnectTimer = null }
  }
}

export const viewsTransport: ViewsTransport = new ViewsTransportImpl()
