// SseTransport 実装。 /jsonl/stream/all を単一 EventSource で購読、 全 sid event を listener に dispatch。
// 設計判断: ADR-013 iOS 7-day storage cap 耐性、 offset 消失時は backend の uuid dedup fallback を信頼。

import type { SseTransport, SseEventHandler, Unsubscribe } from '../ports/SseTransport.ts'
import type { AnySseEvent } from '../contracts/sse-events.ts'
import { API_BASE } from '../constants.js'

const LS_OFFSETS = 'cpc_v2_jsonl_offsets'  // {sid: byte_offset}

function loadOffsets(): Record<string, number> {
  try {
    const raw = localStorage.getItem(LS_OFFSETS)
    if (!raw) return {}
    const parsed = JSON.parse(raw)
    return parsed && typeof parsed === 'object' ? parsed as Record<string, number> : {}
  } catch { return {} }
}

function saveOffsets(o: Record<string, number>): void {
  try { localStorage.setItem(LS_OFFSETS, JSON.stringify(o)) } catch { /* quota / private mode 等を吸収 */ }
}

function buildFromQuery(offsets: Record<string, number>): string {
  return Object.entries(offsets).map(([sid, pos]) => `${sid}:${pos}`).join(',')
}

function parseLastEventId(eid: string): [string | null, number] {
  // "<sid>:<pos>" 形式、 sid に ':' は含まれないので rsplit
  const idx = eid.lastIndexOf(':')
  if (idx < 0) return [null, 0]
  const sid = eid.slice(0, idx)
  const pos = parseInt(eid.slice(idx + 1), 10)
  return [sid, Number.isFinite(pos) ? pos : 0]
}

class SseTransportImpl implements SseTransport {
  private es: EventSource | null = null
  private offsets: Record<string, number> = loadOffsets()
  private handlers = new Set<SseEventHandler>()
  state: 'idle' | 'connecting' | 'open' | 'reconnecting' | 'closed' = 'idle'

  subscribe(handler: SseEventHandler): Unsubscribe {
    this.handlers.add(handler)
    if (this.es === null) this.start()
    return () => {
      this.handlers.delete(handler)
      if (this.handlers.size === 0) this.stop()
    }
  }

  private start(): void {
    if (this.es) return
    this.state = 'connecting'
    const fromQ = buildFromQuery(this.offsets)
    const url = `${API_BASE}/jsonl/stream/all${fromQ ? `?from=${fromQ}` : ''}`
    this.es = new EventSource(url)
    this.es.onopen = () => { this.state = 'open' }
    this.es.onmessage = (ev: MessageEvent<string>) => this.onMessage(ev)
    this.es.onerror = () => {
      // EventSource 自動 reconnect が回るので state だけ更新
      if (this.es?.readyState === EventSource.CLOSED) this.state = 'closed'
      else this.state = 'reconnecting'
    }
  }

  stop(): void {
    this.flushOffsets()
    if (this.es) { this.es.close(); this.es = null }
    this.state = 'closed'
  }

  bumpReconnect(): void {
    if (this.es) { this.es.close(); this.es = null }
    this.start()
  }

  flushOffsets(): void {
    saveOffsets(this.offsets)
  }

  private onMessage(ev: MessageEvent<string>): void {
    let event: AnySseEvent
    try { event = JSON.parse(ev.data) as AnySseEvent } catch { return }
    if (ev.lastEventId && ev.lastEventId.includes(':')) {
      const [sid, pos] = parseLastEventId(ev.lastEventId)
      if (sid) {
        this.offsets[sid] = Math.floor(pos)
        saveOffsets(this.offsets)
      }
    }
    for (const handler of this.handlers) {
      try { handler(event) } catch (e) { console.warn('[sse] handler threw', e) }
    }
  }
}

export const sseTransport: SseTransport = new SseTransportImpl()
