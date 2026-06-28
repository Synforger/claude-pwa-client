// SSE event union 型と type narrowing。
// contracts/*.ts (= codegen) から型を借りて domain で再 export する形にし、 features / state / registry
// 層は本 file 経由でのみ AnySseEvent を扱う (= contracts/ への直接依存を減らす、 ADR-010)。

import type { AnySseEvent, SseEventType } from '../contracts/sse-events.ts'

export type { AnySseEvent, SseEventType }
export { SSE_EVENT_TYPES, SSE_EVENTS_SCHEMA_VERSION } from '../contracts/sse-events.ts'

/** 描画の振り分け先カテゴリ (= contracts schema の render_target と一致、 純粋関数で判定)。 */
export type RenderTarget = 'chat' | 'status_bar' | 'overlay' | 'skip'

const TARGET_BY_TYPE: Record<SseEventType, RenderTarget> = {
  user_message: 'chat',
  assistant: 'chat',
  result: 'chat',
  ask_user_question: 'chat',
  task_notification: 'chat',
  system: 'chat',
  system_error: 'chat',
  hook_error: 'chat',
  system_note: 'chat',
  attachment: 'chat',
  budget: 'status_bar',
  mode: 'status_bar',
  permission_mode: 'status_bar',
  pr_link: 'status_bar',
  turn_duration: 'chat',
  stop_hook_summary: 'skip',
  away_summary: 'skip',
}

export function renderTargetOf(event: AnySseEvent): RenderTarget {
  return TARGET_BY_TYPE[event.type as SseEventType] ?? 'skip'
}

/** schema 未定義 type を graceful handle する判定 (= ADR-011)。 frontend は throw せず skip + warn。 */
export function isKnownEventType(t: unknown): t is SseEventType {
  return typeof t === 'string' && t in TARGET_BY_TYPE
}
