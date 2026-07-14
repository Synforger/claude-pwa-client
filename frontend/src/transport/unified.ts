// 統合 transport singleton (= /stream/unified、 2026-07-14 電力効率工事)。
//
// 旧構成の SSE/WS 4-5 本 (= sse.ts + sse-sessions-status + sse-sessions-overview +
// sse-subagents + ws-views) を 1 本の SSE + 制御 POST に畳む。 wire 仕様は
// contracts/schema/http-endpoints.yaml の /stream/unified、 protocol 解説は
// docs/internals/protocol/streams.md § /stream/unified。
//
// 電力設計 (= 本 file がクライアント側で守る不変条件):
//   - jsonl channel は「購読宣言した sid」 だけ受ける (= 見てないセッションの巨大
//     tool_result が無線にも main thread にも届かない)
//   - offset は frame 内 pos で毎 frame 前進、 永続化は 1s debounce + hidden 同期 flush
//     (= 旧 sse.ts の毎 event 同期 setItem を廃止)
//   - keep-alive 1 心拍 / 25s、 生存監視は 65s watchdog (= _sse.ts と同値)
//
// consumer は transport/select.ts 経由で旧 singleton と同じ interface を受け取る
// (= 切替は select.ts の 1 点、 rollback は localStorage cpc_transport=legacy)。

import { API_BASE } from '../constants.js'
import { httpClient } from './http.ts'
import { registerConnection, notifyConnectionChange } from './connectionStatus.js'

type Handler = (data: unknown) => void
type State = 'idle' | 'connecting' | 'open' | 'reconnecting' | 'closed'

const LS_OFFSETS = 'cpc_v2_jsonl_offsets'   // {sid: byte_offset} (= 旧 sse.ts と同 key、 移行不要)
const LS_STATUS = 'cpc_last_all_status'     // 起動 hydrate 用 (= 旧 sse-sessions-status と同 key)
const OFFSET_PERSIST_DEBOUNCE_MS = 1_000
const LIVENESS_TIMEOUT_MS = 65_000
const LIVENESS_CHECK_MS = 15_000
const RECONNECT_DELAY_MS = 3_000

function loadOffsets(): Record<string, number> {
  try {
    const raw = localStorage.getItem(LS_OFFSETS)
    const parsed = raw ? JSON.parse(raw) : null
    return parsed && typeof parsed === 'object' ? parsed as Record<string, number> : {}
  } catch { return {} }
}

class UnifiedTransport {
  // 接続 id: タブ生存中は固定 (= 再接続でも同じ id、 control POST の宛先)
  private connId: string = (typeof crypto !== 'undefined' && crypto.randomUUID)
    ? crypto.randomUUID().replace(/-/g, '').slice(0, 16)
    : Math.random().toString(36).slice(2, 18)

  private es: EventSource | null = null
  state: State = 'idle'
  private lastEventAt = 0

  // --- desired state (= 再接続時に query / hello 後 control で必ず再主張する) ---
  private jsonlSids = new Set<string>()
  private viewSid: string | null = null
  private subagentsSid: string | null = null

  // --- channel handlers + 遅参 subscriber への直近 payload 再配布 (= #184 と同規約) ---
  private jsonlHandlers = new Set<Handler>()
  private statusHandlers = new Set<Handler>()
  private overviewHandlers = new Set<Handler>()
  private subagentsHandlers = new Map<string, Set<Handler>>()
  private lastStatus: unknown
  private lastOverview: unknown
  private lastSubagents = new Map<string, unknown>()

  // --- offsets (= 1s debounce 永続化、 hidden で同期 flush) ---
  private offsets: Record<string, number> = loadOffsets()
  private offsetTimer: ReturnType<typeof setTimeout> | null = null

  private reconnectTimer: ReturnType<typeof setTimeout> | null = null
  private livenessTimer: ReturnType<typeof setInterval> | null = null
  private unregConn: (() => void) | null = null

  // ---------------------------------------------------------------- lifecycle

  private hasSubscribers(): boolean {
    return this.jsonlHandlers.size > 0 || this.statusHandlers.size > 0
      || this.overviewHandlers.size > 0 || this.subagentsHandlers.size > 0
  }

  private ensureStarted(): void {
    if (this.es || !this.hasSubscribers()) return
    this.start()
  }

  private buildUrl(): string {
    const parts: string[] = [`conn=${encodeURIComponent(this.connId)}`]
    const subs = Array.from(this.jsonlSids)
      .map(sid => `${sid}:${Math.floor(this.offsets[sid] ?? -1) >= 0 ? Math.floor(this.offsets[sid]) : ''}`)
      .map(s => s.endsWith(':') ? s.slice(0, -1) : s)
    if (subs.length > 0) parts.push(`jsonl=${encodeURIComponent(subs.join(','))}`)
    if (this.viewSid) parts.push(`view=${encodeURIComponent(this.viewSid)}`)
    return `${API_BASE}/stream/unified?${parts.join('&')}`
  }

  private start(): void {
    if (this.es) return
    this.state = 'connecting'
    this.lastEventAt = Date.now()
    const es = new EventSource(this.buildUrl())
    this.es = es
    es.onopen = () => {
      this.state = 'open'
      this.lastEventAt = Date.now()
      notifyConnectionChange()
    }
    es.onmessage = (ev: MessageEvent<string>) => this.onMessage(ev)
    es.onerror = () => {
      // EventSource の自動再接続は「接続時の URL」 を使い回すため、 offset が進んだ後の
      // 再接続で古い区間を再 replay してしまう。 自前で閉じて最新 offsets の URL で張り直す。
      if (this.es !== es) return
      this.state = es.readyState === EventSource.CLOSED ? 'closed' : 'reconnecting'
      notifyConnectionChange()
      try { es.close() } catch { /* ignore */ }
      this.es = null
      this.scheduleReconnect(RECONNECT_DELAY_MS)
    }
    if (this.livenessTimer === null) {
      this.livenessTimer = setInterval(() => {
        const visible = typeof document === 'undefined' || document.visibilityState === 'visible'
        if (!visible || !this.hasSubscribers() || this.es === null) return
        if (Date.now() - this.lastEventAt > LIVENESS_TIMEOUT_MS) this.bumpReconnect()
      }, LIVENESS_CHECK_MS)
    }
    if (this.unregConn === null) {
      this.unregConn = registerConnection(() => !!this.es && this.es.readyState === EventSource.OPEN)
    }
  }

  stop(): void {
    if (this.reconnectTimer) { clearTimeout(this.reconnectTimer); this.reconnectTimer = null }
    if (this.es) { try { this.es.close() } catch { /* ignore */ } this.es = null }
    if (this.livenessTimer !== null) { clearInterval(this.livenessTimer); this.livenessTimer = null }
    if (this.unregConn) { this.unregConn(); this.unregConn = null }
    this.flushOffsets()
    this.state = 'closed'
    notifyConnectionChange()
  }

  bumpReconnect(): void {
    if (this.reconnectTimer) { clearTimeout(this.reconnectTimer); this.reconnectTimer = null }
    if (this.es) { try { this.es.close() } catch { /* ignore */ } this.es = null }
    if (this.hasSubscribers()) this.start()
  }

  private scheduleReconnect(delayMs: number): void {
    if (this.reconnectTimer || !this.hasSubscribers()) return
    this.reconnectTimer = setTimeout(() => {
      this.reconnectTimer = null
      if (this.hasSubscribers() && this.es === null) this.start()
    }, delayMs)
  }

  // ---------------------------------------------------------------- dispatch

  private onMessage(ev: MessageEvent<string>): void {
    this.lastEventAt = Date.now()
    if (!ev.data) return
    let frame: Record<string, unknown>
    try { frame = JSON.parse(ev.data) } catch { return }
    const ch = frame.ch
    if (ch === 'sys') {
      if (frame.type === 'hello') this.onHello()
      return  // _hb は lastEventAt 更新のみ
    }
    if (ch === 'jsonl') {
      const event = frame.ev as Record<string, unknown> | undefined
      if (!event) return
      const pos = frame.pos
      const sid = event.sid
      if (typeof pos === 'number' && typeof sid === 'string' && sid) {
        this.offsets[sid] = Math.floor(pos)
        this.schedulePersistOffsets()
      }
      for (const h of this.jsonlHandlers) {
        try { h(event) } catch (e) { console.warn('[unified] jsonl handler threw', e) }
      }
      return
    }
    if (ch === 'status') {
      const data = frame.data
      try { localStorage.setItem(LS_STATUS, JSON.stringify(data)) } catch { /* quota 等は無視 */ }
      this.lastStatus = data
      for (const h of this.statusHandlers) {
        try { h(data) } catch (e) { console.warn('[unified] status handler threw', e) }
      }
      return
    }
    if (ch === 'overview') {
      this.lastOverview = frame.data
      for (const h of this.overviewHandlers) {
        try { h(frame.data) } catch (e) { console.warn('[unified] overview handler threw', e) }
      }
      return
    }
    if (ch === 'subagents') {
      const sid = frame.sid
      if (typeof sid !== 'string') return
      this.lastSubagents.set(sid, frame.data)
      const set = this.subagentsHandlers.get(sid)
      if (set) {
        for (const h of set) {
          try { h(frame.data) } catch (e) { console.warn('[unified] subagents handler threw', e) }
        }
      }
    }
  }

  private onHello(): void {
    // 接続 (再) 確立: server 側 conn は GET query の状態しか知らないので、 query に乗らない
    // desired state (= subagents watch) をここで再主張する。 view は query 済みだが、
    // 接続前に setActiveSid された可能性もあるため冪等に再送する。
    if (this.viewSid) this.control({ op: 'view', sid: this.viewSid })
    if (this.subagentsSid) this.control({ op: 'subagents', sid: this.subagentsSid })
  }

  private control(body: Record<string, unknown>): void {
    httpClient.apiFetch(`/stream/unified/${encodeURIComponent(this.connId)}/control`, {
      method: 'POST', jsonBody: body,
    }).then(res => {
      // 404 = backend 再起動等で conn 消失 → 張り直し (= hello が desired state を再主張)
      if (res.status === 404) this.bumpReconnect()
    }).catch(() => { /* offline 等は watchdog / fg bump に任せる */ })
  }

  // ---------------------------------------------------------------- offsets

  private schedulePersistOffsets(): void {
    if (this.offsetTimer) return
    this.offsetTimer = setTimeout(() => {
      this.offsetTimer = null
      try { localStorage.setItem(LS_OFFSETS, JSON.stringify(this.offsets)) } catch { /* ignore */ }
    }, OFFSET_PERSIST_DEBOUNCE_MS)
  }

  flushOffsets(): void {
    if (this.offsetTimer) { clearTimeout(this.offsetTimer); this.offsetTimer = null }
    try { localStorage.setItem(LS_OFFSETS, JSON.stringify(this.offsets)) } catch { /* ignore */ }
  }

  resetOffset(sid: string): void {
    delete this.offsets[sid]
    this.flushOffsets()
  }

  // ---------------------------------------------------------------- public API

  subscribeJsonl(handler: Handler): () => void {
    this.jsonlHandlers.add(handler)
    this.ensureStarted()
    return () => {
      this.jsonlHandlers.delete(handler)
      if (!this.hasSubscribers()) this.stop()
    }
  }

  /** 購読 sid set の差替 (= タブ切替)。 接続中なら同一接続上で control、 未接続なら次回 query。 */
  setJsonlSids(sids: string[]): void {
    const next = new Set(sids.filter(Boolean))
    const same = next.size === this.jsonlSids.size && Array.from(next).every(s => this.jsonlSids.has(s))
    this.jsonlSids = next
    if (same) return
    if (this.es && this.state === 'open') {
      this.control({
        op: 'jsonl',
        sids: Array.from(next).map(sid => ({
          sid,
          from: Number.isFinite(this.offsets[sid]) ? Math.floor(this.offsets[sid]) : null,
        })),
      })
    }
  }

  subscribeStatus(handler: Handler): () => void {
    this.statusHandlers.add(handler)
    this.ensureStarted()
    if (this.lastStatus !== undefined) {
      try { handler(this.lastStatus) } catch (e) { console.warn('[unified] status late-replay threw', e) }
    }
    return () => {
      this.statusHandlers.delete(handler)
      if (!this.hasSubscribers()) this.stop()
    }
  }

  subscribeOverview(handler: Handler): () => void {
    this.overviewHandlers.add(handler)
    this.ensureStarted()
    if (this.lastOverview !== undefined) {
      try { handler(this.lastOverview) } catch (e) { console.warn('[unified] overview late-replay threw', e) }
    }
    return () => {
      this.overviewHandlers.delete(handler)
      if (!this.hasSubscribers()) this.stop()
    }
  }

  subscribeSubagents(sid: string, handler: Handler): () => void {
    let set = this.subagentsHandlers.get(sid)
    if (!set) { set = new Set(); this.subagentsHandlers.set(sid, set) }
    set.add(handler)
    this.ensureStarted()
    if (this.subagentsSid !== sid) {
      this.subagentsSid = sid
      if (this.es && this.state === 'open') this.control({ op: 'subagents', sid })
    }
    const last = this.lastSubagents.get(sid)
    if (last !== undefined) {
      try { handler(last) } catch (e) { console.warn('[unified] subagents late-replay threw', e) }
    }
    return () => {
      const cur = this.subagentsHandlers.get(sid)
      if (cur) {
        cur.delete(handler)
        if (cur.size === 0) {
          this.subagentsHandlers.delete(sid)
          this.lastSubagents.delete(sid)
          if (this.subagentsSid === sid) {
            this.subagentsSid = null
            if (this.es) this.control({ op: 'subagents', sid: null })
          }
        }
      }
      if (!this.hasSubscribers()) this.stop()
    }
  }

  setActiveSid(sid: string | null): void {
    if (this.viewSid === sid) return
    this.viewSid = sid
    if (this.es && this.state === 'open') this.control({ op: 'view', sid })
  }

  sendStopIntent(sid: string): void {
    if (!sid) return
    this.control({ op: 'stop', sid })
  }
}

export const unifiedTransport = new UnifiedTransport()

// ---- 旧 singleton interface への adapter (= consumer 側 diff を最小化、 select.ts が配る) ----

/** transport/sse.ts (SseTransport) 互換 + setSubscribedSids 拡張。 */
export const unifiedJsonl = {
  subscribe: (h: Handler) => unifiedTransport.subscribeJsonl(h),
  stop: () => unifiedTransport.stop(),
  bumpReconnect: () => unifiedTransport.bumpReconnect(),
  flushOffsets: () => unifiedTransport.flushOffsets(),
  resetOffset: (sid: string) => unifiedTransport.resetOffset(sid),
  setSubscribedSids: (sids: string[]) => unifiedTransport.setJsonlSids(sids),
  get state() { return unifiedTransport.state },
}

/** _sse.ts factory (SseInstance) 互換 (= sessions-status / sessions-overview の代替)。 */
export const unifiedStatusSse = {
  name: 'unified:status',
  subscribe: (h: Handler) => unifiedTransport.subscribeStatus(h),
  stop: () => { /* 共有接続は他 channel が使うので個別 stop しない */ },
  bumpReconnect: () => unifiedTransport.bumpReconnect(),
  get state() { return unifiedTransport.state },
  get hasSubscribers() { return true },
}

export const unifiedOverviewSse = {
  name: 'unified:overview',
  subscribe: (h: Handler) => unifiedTransport.subscribeOverview(h),
  stop: () => { /* 同上 */ },
  bumpReconnect: () => unifiedTransport.bumpReconnect(),
  get state() { return unifiedTransport.state },
  get hasSubscribers() { return true },
}

/** sse-subagents (PerSidSseFactory) 互換。 */
export const unifiedSubagentsSse = {
  subscribe: (sid: string, h: Handler) => unifiedTransport.subscribeSubagents(sid, h),
}

/** ws-views (ViewsTransport) 互換。 start/stop は共有接続の lifecycle に吸収済 = no-op。 */
export const unifiedViews = {
  start: () => { /* 共有 SSE が担う */ },
  stop: () => { /* 同上 */ },
  setActiveSid: (sid: string | null) => unifiedTransport.setActiveSid(sid),
  sendStopIntent: (sid: string) => unifiedTransport.sendStopIntent(sid),
  get state() { return unifiedTransport.state },
}
