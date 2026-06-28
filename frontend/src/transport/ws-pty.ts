// PtyTransport 実装。 /ws/pty/{sid} の WebSocket + heartbeat (= ADR-013、 25s/60s)。
// binary frame は bytes 主経路 (= xterm.js writeUtf8 直渡し)、 副次経路で decoded text も渡す。

import type { PtyTransport, PtyFrame, PtyControlFrame, PtyFrameHandler, Unsubscribe } from '../ports/PtyTransport.ts'
import { API_BASE } from '../constants.js'

const HEARTBEAT_INTERVAL_MS = 25_000
const HEARTBEAT_TIMEOUT_MS = 60_000
const RECONNECT_MIN_MS = 500
const RECONNECT_MAX_MS = 10_000

function wsBaseFrom(httpBase: string): string {
  if (!httpBase) {
    // 同一オリジン相対 (= window.location)
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

type State = 'idle' | 'connecting' | 'open' | 'degraded' | 'reconnecting' | 'closed'

interface Conn {
  ws: WebSocket
  decoder: TextDecoder
  listeners: Set<PtyFrameHandler>
  heartbeat: ReturnType<typeof setInterval> | null
  lastPong: number
  state: State
  reconnectDelay: number
  intentClose: boolean
}

class PtyTransportImpl implements PtyTransport {
  private conns = new Map<string, Conn>()

  connect(sid: string, handler: PtyFrameHandler): Unsubscribe {
    let entry = this.conns.get(sid)
    if (!entry) {
      entry = this.openConn(sid)
      this.conns.set(sid, entry)
    }
    entry.listeners.add(handler)
    return () => {
      const cur = this.conns.get(sid)
      if (!cur) return
      cur.listeners.delete(handler)
      if (cur.listeners.size === 0) this.disconnect(sid)
    }
  }

  sendBytes(sid: string, bytes: Uint8Array): void {
    const entry = this.conns.get(sid)
    if (!entry || entry.ws.readyState !== WebSocket.OPEN) return
    try { entry.ws.send(bytes) } catch (e) { console.warn('[ws-pty] send bytes failed', e) }
  }

  resize(sid: string, rows: number, cols: number): void {
    const entry = this.conns.get(sid)
    if (!entry || entry.ws.readyState !== WebSocket.OPEN) return
    try { entry.ws.send(JSON.stringify({ type: 'resize', rows, cols })) } catch (e) { console.warn('[ws-pty] resize failed', e) }
  }

  disconnect(sid: string): void {
    const entry = this.conns.get(sid)
    if (!entry) return
    entry.intentClose = true
    if (entry.heartbeat) clearInterval(entry.heartbeat)
    try { entry.ws.close(1000, 'client-intent') } catch { /* ignore */ }
    entry.state = 'closed'
    this.conns.delete(sid)
  }

  stateOf(sid: string): State {
    return this.conns.get(sid)?.state ?? 'idle'
  }

  private openConn(sid: string): Conn {
    const url = `${WS_BASE}/ws/pty/${encodeURIComponent(sid)}`
    const ws = new WebSocket(url)
    ws.binaryType = 'arraybuffer'
    const entry: Conn = {
      ws,
      decoder: new TextDecoder('utf-8', { fatal: false, ignoreBOM: false }),
      listeners: new Set(),
      heartbeat: null,
      lastPong: nowMs(),
      state: 'connecting',
      reconnectDelay: RECONNECT_MIN_MS,
      intentClose: false,
    }
    ws.onopen = () => {
      entry.state = 'open'
      entry.lastPong = nowMs()
      entry.reconnectDelay = RECONNECT_MIN_MS
      this.startHeartbeat(sid, entry)
    }
    ws.onmessage = (ev: MessageEvent) => this.onMessage(sid, entry, ev)
    ws.onclose = () => this.onClose(sid, entry)
    ws.onerror = () => { /* onclose で再接続するので何もしない */ }
    return entry
  }

  private startHeartbeat(sid: string, entry: Conn): void {
    if (entry.heartbeat) clearInterval(entry.heartbeat)
    entry.heartbeat = setInterval(() => {
      const now = nowMs()
      if (now - entry.lastPong > HEARTBEAT_TIMEOUT_MS) {
        entry.state = 'degraded'
        console.warn('[ws-pty] heartbeat timeout, force reconnect', sid)
        try { entry.ws.close(4000, 'heartbeat-timeout') } catch { /* ignore */ }
        return
      }
      if (entry.ws.readyState === WebSocket.OPEN) {
        try { entry.ws.send(JSON.stringify({ type: 'ping', ts: now })) } catch { /* ignore */ }
      }
    }, HEARTBEAT_INTERVAL_MS)
  }

  private onMessage(sid: string, entry: Conn, ev: MessageEvent): void {
    if (typeof ev.data === 'string') {
      let parsed: unknown
      try { parsed = JSON.parse(ev.data) } catch { return }
      if (parsed && typeof parsed === 'object' && (parsed as { type?: string }).type === 'pong') {
        entry.lastPong = nowMs()
        return
      }
      // schema (= ws-channels.yaml § pty server_to_client) の oneOf で型制約済、 ここでは narrow せず control 扱い
      const data = parsed as PtyControlFrame['data']
      const frame: PtyControlFrame = { kind: 'control', data }
      for (const h of entry.listeners) { try { h(frame) } catch (e) { console.warn('[ws-pty] handler threw', e) } }
    } else {
      const bytes = new Uint8Array(ev.data as ArrayBuffer)
      const text = entry.decoder.decode(bytes, { stream: true })
      const frame: PtyFrame = { kind: 'data', bytes, text }
      for (const h of entry.listeners) { try { h(frame) } catch (e) { console.warn('[ws-pty] handler threw', e) } }
    }
  }

  private onClose(sid: string, entry: Conn): void {
    if (entry.heartbeat) { clearInterval(entry.heartbeat); entry.heartbeat = null }
    if (entry.intentClose) {
      entry.state = 'closed'
      return
    }
    entry.state = 'reconnecting'
    const delay = entry.reconnectDelay + Math.random() * 250  // jitter
    setTimeout(() => {
      if (!this.conns.has(sid)) return  // disconnect された
      const fresh = this.openConn(sid)
      fresh.listeners = entry.listeners  // listener を引き継ぐ
      fresh.reconnectDelay = Math.min(entry.reconnectDelay * 2, RECONNECT_MAX_MS)
      this.conns.set(sid, fresh)
    }, delay)
  }
}

function nowMs(): number {
  return typeof performance !== 'undefined' && typeof performance.now === 'function'
    ? Math.floor(performance.timeOrigin + performance.now())
    : Date.now()
}

export const ptyTransport: PtyTransport = new PtyTransportImpl()
