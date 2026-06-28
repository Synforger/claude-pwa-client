// /sessions/overview/stream SSE singleton (= 全 sid の busy / pending_question snapshot)。
// features/session-drawer/useSessionsOverview.js が subscribe する。
// 設計判断: ADR-019 (= 4 SSE endpoint 別 singleton + _sse 共通 factory)。

import { createSseSubscriber } from './_sse.ts'

export const sessionsOverviewSse = createSseSubscriber({
  name: 'sessions-overview',
  path: '/sessions/overview/stream',
})
