// /sessions/{sid}/subagents/stream per-sid SSE factory (= ADR-019 拡張)。
// SubagentsModal が active sid で subscribe する。 同 sid の複数 subscribe は同 EventSource を
// 共有 (= refs カウンタ)、 最後の unsubscribe で自動 close。

import { createPerSidSseSubscriber } from './_sse.ts'

export const subagentsSse = createPerSidSseSubscriber({
  name: 'subagents',
  pathTemplate: '/sessions/{sid}/subagents/stream',
})
