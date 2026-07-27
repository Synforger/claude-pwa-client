// transport 実装の選択点 (= unified ⇄ legacy の 1 点切替、 2026-07-14 電力効率工事)。
//
// 既定は unified (= 1 本多重化接続)。 緊急 rollback は DevTools で
// `localStorage.setItem('cpc_transport', 'legacy')` → reload (= 旧 4-5 本構成に戻る。
// backend は旧 endpoint を全部温存しているので新旧どちらの bundle でも動く)。
//
// consumer は本 module からだけ import する (= sse.ts / _sse 系 / ws-views を直接
// import する経路を残すと切替が二重管理になる)。

import { sseTransport } from './sse.ts'
import { sessionsStatusSse } from './sse-sessions-status.ts'
import { sessionsOverviewSse } from './sse-sessions-overview.ts'
import { subagentsSse } from './sse-subagents.ts'
import { viewsTransport } from './ws-views.ts'
import {
  unifiedJsonl,
  unifiedOverviewSse,
  unifiedStatusSse,
  unifiedSubagentsSse,
  unifiedTransport,
  unifiedViews,
} from './unified.ts'

export const unifiedEnabled: boolean = (() => {
  try { return localStorage.getItem('cpc_transport') !== 'legacy' } catch { return true }
})()

/** chat jsonl 経路 (= SseTransport 互換 + setSubscribedSids)。 legacy は全 sid 配信なので
 * setSubscribedSids は no-op (= useChatStream 側は無条件に呼んで良い)。 */
export const chatTransport = unifiedEnabled
  ? unifiedJsonl
  : {
      // spread はクラス instance の prototype メソッドを落とすので明示 delegation
      subscribe: (h: Parameters<typeof sseTransport.subscribe>[0]) => sseTransport.subscribe(h),
      stop: () => sseTransport.stop(),
      bumpReconnect: () => sseTransport.bumpReconnect(),
      flushOffsets: () => sseTransport.flushOffsets(),
      resetOffset: (sid: string) => sseTransport.resetOffset(sid),
      getOffset: (sid: string) => sseTransport.getOffset(sid),
      advanceOffset: (sid: string, pos: number) => sseTransport.advanceOffset(sid, pos),
      setSubscribedSids: (_sids: string[]) => { /* legacy = 全 sid 配信 */ },
      get state() { return sseTransport.state },
    }

export const statusSse = unifiedEnabled ? unifiedStatusSse : sessionsStatusSse
export const overviewSse = unifiedEnabled ? unifiedOverviewSse : sessionsOverviewSse
export const subagentsStreamSse = unifiedEnabled ? unifiedSubagentsSse : subagentsSse
export const viewsChannel = unifiedEnabled ? unifiedViews : viewsTransport

/** lifecycle.ts の fg/bg bump 用: unified は 1 接続 bump、 legacy は従来の全 singleton bump。 */
export { unifiedTransport }
