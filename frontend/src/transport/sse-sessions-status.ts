// /sessions/status/stream SSE singleton (= 全 sid の model / ctx_pct / plan_mode 等 snapshot)。
// features/status-bar/useStatus.js が subscribe する。
// 設計判断: ADR-019 (= 4 SSE endpoint 別 singleton + _sse 共通 factory)。

import { createSseSubscriber } from './_sse.ts'

export const sessionsStatusSse = createSseSubscriber({
  name: 'sessions-status',
  path: '/sessions/status/stream',
})
