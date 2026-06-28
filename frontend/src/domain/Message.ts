// Message union 型 + 純粋関数。 React / DOM 非依存。
// v1 では components/MessageItem.jsx 内で role 分岐していたが、 v2 では本 union と純粋判定に集約する。

import type { ToolUse, ToolResult } from './Tool.ts'

/** Markdown / plain text を持つ user 発話。 server-of-truth 確定後 uuid が付く (= ADR-006 server-of-truth)。 */
export interface UserMessage {
  role: 'user'
  /** server 採番 uuid。 optimistic な未確定 user message は uuid を持たず ephemeral 側で扱う。 */
  uuid: string
  text: string
  ts?: number
  parentUuid?: string | null
}

/** assistant 応答 (= text / thinking / tool_use ブロックの集合体)。 */
export interface AgentMessage {
  role: 'agent'
  uuid: string
  text: string
  thinking?: string | null
  tools: ToolUse[]
  /** assistant turn のメタ情報 (= result event から確定後に充填)。 stop_reason 等。 */
  meta?: AgentMessageMeta | null
  /** streaming 中なら true、 result 受領で false 化。 */
  streaming?: boolean
  askUserQuestion?: AskUserQuestionState | null
}

export interface AgentMessageMeta {
  stop_reason?: string | null
  is_error?: boolean
  cost_usd?: number | null
  num_turns?: number | null
  duration_ms?: number | null
  usage?: Record<string, unknown> | null
  modelUsage?: Record<string, unknown> | null
  stop_details?: Record<string, unknown> | null
}

export interface AskUserQuestionState {
  tool_use_id: string
  questions: Array<Record<string, unknown>>
  answered: boolean
  selectedAnswer: string | null
}

/** system kind (= compact / api_error / hook_error / system_note / attachment / task)。 */
export type SystemKind = 'compact' | 'api_error' | 'hook_error' | 'system_note' | 'attachment' | 'task'

export interface SystemMessage {
  role: 'system'
  /** 同種 system message を 1 件に dedup する key (= 同 uuid 重複受信を 1 件に潰す)。 */
  uuid: string | null
  kind: SystemKind
  /** kind ごとの payload は表示側で見るので汎用 dict。 */
  [extra: string]: unknown
}

/** 描画される全 message の union。 ToolResult は assistant の tools 配下に同居するため独立しない。 */
export type Message = UserMessage | AgentMessage | SystemMessage

// ---- 判別 ----

export function isUserMessage(m: Message): m is UserMessage {
  return m.role === 'user'
}

export function isAgentMessage(m: Message): m is AgentMessage {
  return m.role === 'agent'
}

export function isSystemMessage(m: Message): m is SystemMessage {
  return m.role === 'system'
}

/** 永続化可能か (= uuid 確定済の user/agent message のみ persist、 system は kind 別、 optimistic は除外)。 */
export function isPersistableMessage(m: Message): boolean {
  if (m.role === 'user') return typeof m.uuid === 'string' && m.uuid.length > 0
  if (m.role === 'agent') return typeof m.uuid === 'string' && m.uuid.length > 0
  if (m.role === 'system') return m.uuid !== null && m.uuid.length > 0
  return false
}

/** dedup key (= sid + uuid + role)。 reconnect replay 時の重複 no-op 判定に使う。 */
export function dedupKey(sid: string, m: Message): string {
  return `${sid}|${m.role}|${m.uuid ?? ''}`
}

/** assistant tool list を ToolResult で reconcile する (= 純粋、 元 array を変更しない)。
 *  v1 の processStreamEvent.js から純粋部分を移送。 */
export function attachToolResults(tools: ToolUse[], results: ToolResult[]): { tools: ToolUse[]; changed: boolean } {
  if (results.length === 0) return { tools, changed: false }
  let changed = false
  const next = tools.map(t => {
    const r = results.find(x => x.tool_use_id === t.id)
    if (!r) return t
    changed = true
    return { ...t, result: { content: r.content, is_error: !!r.is_error } }
  })
  return { tools: changed ? next : tools, changed }
}
