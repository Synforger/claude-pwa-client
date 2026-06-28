// SSE 接続の port interface。
// /jsonl/stream/all (= 全 session 統合) を購読する単一 EventSource を抽象化する。
// 実装: transport/sse.ts (= Phase 5)。
// 関連 ADR: ADR-010 hexagonal / ADR-012 corr_id envelope / ADR-013 BFCache 対応。

import type { AnySseEvent } from '../contracts/sse-events.ts'

/** subscriber が返す cleanup 関数。 React の useEffect cleanup と同じ流儀。 */
export type Unsubscribe = () => void

/** subscriber callback。 event は必ず sid + corr_id を含む (= envelope global required、 ADR-012)。 */
export type SseEventHandler = (event: AnySseEvent) => void

export interface SseTransport {
  /** SSE 購読開始。 既に open ならハンドラ追加のみ。 */
  subscribe(handler: SseEventHandler): Unsubscribe

  /** offset を localStorage に flush + EventSource close。 bg 遷移 / freeze / unmount 経路で呼ぶ。 */
  stop(): void

  /** transport rebuild。 BFCache 復帰 / 切断検知時に reconnect の起点。 */
  bumpReconnect(): void

  /** localStorage の offset を即 flush (= visibility hidden / freeze 時)。 */
  flushOffsets(): void

  /** デバッグ用: 現在の接続状態 (= idle / connecting / open / reconnecting / closed)。 lifecycle.yaml と一致。 */
  readonly state: 'idle' | 'connecting' | 'open' | 'reconnecting' | 'closed'
}
