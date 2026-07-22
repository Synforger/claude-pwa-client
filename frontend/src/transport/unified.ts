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

  // --- offsets (= in-memory は毎 frame 前進 / 永続化は useChatStorage のメッセージ保存に結合) ---
  private offsets: Record<string, number> = loadOffsets()

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
    // offset はここで永続化しない (= in-memory は最新受信位置で、 描画・永続化した位置より
    // 先行し得る)。 永続化は useChatStorage のメッセージ保存に結合済 (= flushOffsets)。
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
        // 単調ガード: replay と live pump の並走で古い pos の frame が後着し得る
        // (= server は pump 先行で隙間ゼロを優先、 重複側は client で吸収する規約)。
        // offset を巻き戻すと次回接続の replay が無駄に太る。
        //
        // in-memory の offset は毎 frame 前進させる (= live 再接続は React state に載ってる
        // 位置から続けたいので最新を使う)。 ただし **localStorage への永続化はここでしない**:
        // 永続 offset は「描画・永続化したメッセージの位置」 に一致させる必要がある (= 受信で
        // 前進させて永続化すると、 デバウンス保存が追いつく前の区間が localStorage に無いまま
        // offset だけ先行 → リロード replay で中抜けになる)。 永続化は useChatStorage の
        // メッセージ保存成功時に flushOffsets() で行う (= 保存は turn 確定時なので、 その時点の
        // in-memory offset = 最後に確定・永続化したメッセージの位置)。
        if (Math.floor(pos) > (this.offsets[sid] ?? -1)) {
          this.offsets[sid] = Math.floor(pos)
        }
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
    // 接続 (再) 確立: desired state を**全部**冪等に再主張する。 server の op=jsonl は
    // 「既購読 sid は added に入らない = 重複 replay しない」 ので、 query で購読済みでも
    // 再送は無害。 逆に query 構築後〜open の間に setJsonlSids された場合 (= 初回接続で
    // 実際に起きたレース: jsonl= 無し接続 → 購読ゼロのままチャットが凍る、 2026-07-15
    // access log で確認) はこの再主張だけが購読を成立させる。
    this.assertJsonlSubs()
    if (this.viewSid) this.control({ op: 'view', sid: this.viewSid })
    if (this.subagentsSid) this.control({ op: 'subagents', sid: this.subagentsSid })
  }

  private control(body: Record<string, unknown>, opts?: { keepalive?: boolean }): void {
    httpClient.apiFetch(`/stream/unified/${encodeURIComponent(this.connId)}/control`, {
      method: 'POST', jsonBody: body, ...(opts?.keepalive ? { keepalive: true } : {}),
    }).then(res => {
      // 404 = backend 再起動等で conn 消失 → 張り直し (= hello が desired state を再主張)
      if (res.status === 404) this.bumpReconnect()
    }).catch(() => { /* offline 等は watchdog / fg bump に任せる */ })
  }

  /** hidden 遷移時: backend の「見てる」 登録だけ即時解除する (= 通知抑制の解除)。
   *
   * 旧 /views/ws は hidden で WS ごと閉じて登録が消えていた。 統合接続は hidden でも
   * すぐには切れないため、 明示的に view null を届けないと「裏に置いたタブが通知を
   * 抑制し続ける」 (= AskUserQuestion が鳴らない) 窓が開く。 desired (= viewSid) は
   * 保持したまま送る: fg 復帰時の bump → hello 再主張が登録を復元する。 keepalive で
   * hidden 遷移中でも送達させる。 */
  suspendView(): void {
    if (this.viewSid && this.es) {
      this.control({ op: 'view', sid: null }, { keepalive: true })
    }
  }

  // ---------------------------------------------------------------- offsets

  /** 永続 offset を現在の in-memory 値で書く。 呼び出しは useChatStorage の**メッセージ保存
   *  成功時**に結合済 (= 永続 offset を「描画・永続化した位置」 に一致させる、 中抜け根治)。 */
  flushOffsets(): void {
    try { localStorage.setItem(LS_OFFSETS, JSON.stringify(this.offsets)) } catch { /* ignore */ }
  }

  /** sid の現在 offset (= 描画・永続化した位置)。 GET /jsonl/history の from に渡す。 */
  getOffset(sid: string): number {
    return this.offsets[sid] ?? 0
  }

  /** GET で権威スナップショットを取り込んだ後、 offset をそこまで前進させる (= 単調)。
   *  以降 stream の replay 起点がそこになり、 stream は差分だけを流す。 */
  advanceOffset(sid: string, pos: number): void {
    if (Math.floor(pos) > (this.offsets[sid] ?? -1)) this.offsets[sid] = Math.floor(pos)
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
    this.assertJsonlSubs()
  }

  /** 購読宣言を送り、 応答の subscribed で成立を検証する (= 未成立ならリトライ)。
   *
   * backend は「知らない sid」 の購読を黙って落とす (= 新規タブ / fork 直後は POST
   * /sessions の登録と購読宣言がほぼ同時に走り、 まれに購読側が先着して捨てられる)。
   * 応答検証 + 500ms 段階リトライで、 登録が追いつき次第 購読が成立する。 */
  private assertJsonlSubs(attempt = 0): void {
    if (!this.es || this.state !== 'open' || this.jsonlSids.size === 0) return
    const desired = Array.from(this.jsonlSids)
    httpClient.apiFetch(`/stream/unified/${encodeURIComponent(this.connId)}/control`, {
      method: 'POST',
      jsonBody: {
        op: 'jsonl',
        sids: desired.map(sid => ({
          sid,
          from: Number.isFinite(this.offsets[sid]) ? Math.floor(this.offsets[sid]) : null,
        })),
      },
    }).then(async res => {
      if (res.status === 404) { this.bumpReconnect(); return }
      const data = res.ok ? await res.json().catch(() => null) : null
      const got = new Set<string>((data && (data as { subscribed?: string[] }).subscribed) || [])
      // 現時点の desired と照合 (= リトライ待ちの間にタブ切替されていたら古い分は追わない)
      const missing = desired.filter(s => this.jsonlSids.has(s) && !got.has(s))
      if ((missing.length > 0 || !res.ok) && attempt < 3) {
        setTimeout(() => this.assertJsonlSubs(attempt + 1), 500 * (attempt + 1))
      } else if (missing.length > 0) {
        console.warn('[unified] jsonl subscription not established after retries', missing)
      }
    }).catch(() => {
      if (attempt < 3) setTimeout(() => this.assertJsonlSubs(attempt + 1), 500 * (attempt + 1))
    })
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

  sendStopIntent(sid: string, attempt = 0): void {
    if (!sid) return
    // Stop は「押したのに止まらない」 が一番信頼を損ねる操作。 旧 /views/ws は TCP 保証で
    // 届けていたので、 POST 化に合わせて再送を明示する: 失敗 (= network / 5xx) は
    // 300ms → 900ms の 2 回まで再送。 backend 側 user_stopped は冪等なので重複送達は無害。
    // 404 (= conn 消失) は control() 共通の bumpReconnect が走るので、 再送は再接続後の
    // conn に対して行われる。
    const RETRIES = 2
    httpClient.apiFetch(`/stream/unified/${encodeURIComponent(this.connId)}/control`, {
      method: 'POST', jsonBody: { op: 'stop', sid },
    }).then(res => {
      if (res.status === 404) {
        this.bumpReconnect()
        if (attempt < RETRIES) setTimeout(() => this.sendStopIntent(sid, attempt + 1), 300 * (3 ** attempt))
        return
      }
      if (!res.ok && attempt < RETRIES) {
        setTimeout(() => this.sendStopIntent(sid, attempt + 1), 300 * (3 ** attempt))
      }
    }).catch(() => {
      if (attempt < RETRIES) {
        setTimeout(() => this.sendStopIntent(sid, attempt + 1), 300 * (3 ** attempt))
      } else {
        console.warn('[unified] stop intent delivery failed after retries', sid)
      }
    })
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
  getOffset: (sid: string) => unifiedTransport.getOffset(sid),
  advanceOffset: (sid: string, pos: number) => unifiedTransport.advanceOffset(sid, pos),
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
