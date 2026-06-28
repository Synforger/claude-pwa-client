// 不変条件 / 純粋判定の集約。 React / DOM 非依存。
// 1 つの場所で「同 (sid, uuid) 重複は no-op」「optimistic は ephemeral」 等の規約を表現し、
// state / features / registry / transport がそれを呼び出す形にする。

import type { Message } from './Message.ts'
import type { AnySseEvent } from './Event.ts'

/** 同 (sid, uuid) の event が既に観測済かを判定する高頻度ヘルパ。 */
export function isDuplicateEvent(seenKeys: Set<string>, sid: string, event: AnySseEvent): boolean {
  // sid は envelope で必ず付くが、 念のため event 側 sid を優先
  const evSid = (event as { sid?: string }).sid ?? sid
  const uuid = (event as { uuid?: string }).uuid
  if (!uuid) return false
  return seenKeys.has(`${evSid}|${uuid}`)
}

/** isDuplicateEvent の counterpart: 観測した event を seenKeys に記録 (= 副作用は呼び出し側)。 */
export function eventDedupKey(sid: string, event: AnySseEvent): string | null {
  const evSid = (event as { sid?: string }).sid ?? sid
  const uuid = (event as { uuid?: string }).uuid
  if (!uuid) return null
  return `${evSid}|${uuid}`
}

/** corr_id が 8 hex 形式か (= ADR-012 envelope 整合性のバリデーション、 開発時 inspector で使う)。 */
export function isValidCorrId(c: unknown): c is string {
  return typeof c === 'string' && /^[0-9a-f]{8}$/.test(c)
}

/** 「optimistic で表示するが永続化はしない」 判定 (= state/messages.js と state/ephemeral.js の振り分け根拠)。 */
export function isEphemeralOnly(m: Message): boolean {
  // uuid が空 / null は ephemeral 限定 (= server から確定 uuid が来るまで persist 不可)
  if (m.role === 'user' || m.role === 'agent') {
    return typeof m.uuid !== 'string' || m.uuid.length === 0
  }
  if (m.role === 'system') {
    return m.uuid === null || m.uuid.length === 0
  }
  return false
}

/** harness XML (= <command-name> / <local-command-*> / <task-notification>) の user text に対する非ユーザ判定。
 *  backend が events.py で skip 済なので frontend では通常使わないが、 万一 raw text が user_message として
 *  来た場合の保険として domain layer に置く (= ADR-005 機能漏れ防止)。 */
const HARNESS_XML_PATTERN = /^\s*<(command-name|command-message|command-args|local-command-[a-z-]+|task-notification)\b/

export function looksLikeHarnessXml(text: string): boolean {
  return HARNESS_XML_PATTERN.test(text)
}

const INTERRUPT_MARKER = /^\s*\[request interrupted by user\]\s*$/i

export function isInterruptMarker(text: string): boolean {
  return INTERRUPT_MARKER.test(text)
}
