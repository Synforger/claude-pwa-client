// SSE singleton 共通 factory (= ADR-017 / _store.js / _registry.js と対称な共通化 pattern、 ADR-019)。
// W1 で立てた sse.ts (= /jsonl/stream/all 専用) は別経路 (= offset 管理 / lastEventId parse) を持つので
// 本 factory には乗せず、 別 SSE (= /sessions/overview/stream / /sessions/status/stream /
// /sessions/{sid}/subagents/stream) を本 factory で生成する。
//
// 設計上の役割:
//   - features 配下から fetch / EventSource を直書きさせない (= ADR-010 lint)
//   - 各 SSE singleton が同じ subscribe(handler) interface を持つ (= mock 可能、 ports/SseTransport
//     と整合)
//   - lifecycle (= reconnect / bg / fg / pageshow) を 1 factory で扱う (= ADR-013 BFCache 対応)
//   - W3 observability の inspector が「全 SSE singleton の現在状態を 1 経路で読む」 入口

import { API_BASE } from '../constants.js'

type State = 'idle' | 'connecting' | 'open' | 'reconnecting' | 'closed'
type Handler = (data: unknown) => void

interface SseInstance {
  readonly name: string
  readonly state: State
  subscribe(handler: Handler): () => void
  stop(): void
  bumpReconnect(): void
}

const REGISTRY = new Map<string, SseInstance>()

interface Options {
  /** SSE singleton 名 (= observability で識別、 _sse REGISTRY key)。 */
  name: string
  /** API_BASE 連結後の endpoint path (= 例 '/sessions/overview/stream')。 */
  path: string
  /** EventSource onmessage の data (= JSON.parsed) を変換して dispatch する hook、 省略時は raw を返す。 */
  transform?: (raw: unknown) => unknown
  /** auto-reconnect 戦略。 EventSource 標準の 3s 自動再接続を信頼するなら何も書かない。 readyState===CLOSED 時に手動 bump したい場合は bumpOnClosed: true。 */
  bumpOnClosed?: boolean
}

export function createSseSubscriber(opts: Options): SseInstance {
  const { name, path, transform, bumpOnClosed = true } = opts
  let es: EventSource | null = null
  let state: State = 'idle'
  const handlers = new Set<Handler>()

  function start() {
    if (es) return
    state = 'connecting'
    const url = `${API_BASE}${path}`
    es = new EventSource(url)
    es.onopen = () => { state = 'open' }
    es.onmessage = (ev: MessageEvent<string>) => {
      if (!ev.data) return
      let raw: unknown
      try { raw = JSON.parse(ev.data) } catch { return }
      const data = transform ? transform(raw) : raw
      for (const h of handlers) {
        try { h(data) } catch (e) { console.warn(`[sse:${name}] handler threw`, e) }
      }
    }
    es.onerror = () => {
      if (es?.readyState === EventSource.CLOSED) {
        state = 'closed'
        if (bumpOnClosed) bumpReconnect()
      } else {
        state = 'reconnecting'
      }
    }
  }

  function stop() {
    if (es) { es.close(); es = null }
    state = 'closed'
  }

  function bumpReconnect() {
    if (es) { es.close(); es = null }
    start()
  }

  function subscribe(handler: Handler): () => void {
    handlers.add(handler)
    if (es === null) start()
    return () => {
      handlers.delete(handler)
      if (handlers.size === 0) stop()
    }
  }

  const instance: SseInstance = {
    name,
    get state() { return state },
    subscribe,
    stop,
    bumpReconnect,
  }
  REGISTRY.set(name, instance)
  return instance
}

/** observability 用: 全 SSE singleton の name -> state を返す (= W3 inspector 入口、 ADR-019)。 */
export function getAllSseStates(): Record<string, State> {
  const out: Record<string, State> = {}
  for (const [name, ins] of REGISTRY.entries()) out[name] = ins.state
  return out
}

export function listSseNames(): string[] {
  return Array.from(REGISTRY.keys())
}
