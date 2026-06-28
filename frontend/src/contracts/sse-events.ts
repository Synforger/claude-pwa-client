/** GENERATED FILE — do not edit by hand.
 * Source: contracts/schema/sse-events.yaml
 * Regenerate: cd contracts && npm run codegen:types
 */

export const SSE_EVENTS_SCHEMA_VERSION = "1.0" as const

/** ユーザ発話 (= claude が JSONL の user 行に書いた瞬間) */
export interface UserMessageEvent {
  type: "user_message"
  /** session id (= UI 上のタブ ID) */
  sid: string
  /** server 生成、 dedup key */
  uuid: string
  /** ユーザ発話本文 */
  text: string
  /** W3C trace_id 頭 8 文字、 log 結合用 */
  corr_id: string
  /** 親 message uuid (= fork lineage) */
  parentUuid?: string | null
  /** raw JSONL content (= tool_result 含む list / string 両対応) */
  content?: Record<string, unknown>
  /** epoch ms */
  ts?: number
}

/** claude 応答 (= text / thinking / tool_use ブロック含む) */
export interface AssistantEvent {
  type: "assistant"
  sid: string
  /** Anthropic message.id (= 同 message の delta frame 集約用) */
  uuid: string
  corr_id: string
  message: {
    /** text / thinking / tool_use ブロック list */
    content: ({
        type?: "text" | "thinking" | "tool_use"
      } & Record<string, unknown>)[]
  } & Record<string, unknown>
  parentUuid?: string | null
  /** duration_ms 等の補助メタ */
  meta?: Record<string, unknown>
}

/** ターン完了メタ (= usage / stop_reason / model) */
export interface ResultEvent {
  type: "result"
  sid: string
  /** 親 assistant bubble の uuid */
  uuid?: string
  corr_id: string
  /** end_turn / max_tokens / refusal / pause_turn / model_context_window_exceeded 等 */
  stop_reason: string
  /** input_tokens / output_tokens / cache_* */
  usage?: Record<string, unknown>
  /** model 名 -> usage 写像 */
  modelUsage?: Record<string, unknown>
  /** refusal 時の詳細 (= 4.8 で公開化) */
  stop_details?: Record<string, unknown> | null
  /** stop_reason == refusal で true */
  is_error?: boolean
  total_cost_usd?: number
  num_turns?: number
  duration_ms?: number
}

/** AskUserQuestion tool 呼び出し (= ユーザに選択肢提示) */
export interface AskUserQuestionEvent {
  type: "ask_user_question"
  sid: string
  corr_id: string
  /** Anthropic tool_use id (= 回答時の紐付け key) */
  tool_use_id: string
  /** AskUserQuestion の questions array を含む */
  input: {
    questions?: (Record<string, unknown>)[]
  }
}

/** background task (= Monitor / バックグラウンド Bash / ScheduleWakeup / Cron) の完了通知 */
export interface TaskNotificationEvent {
  type: "task_notification"
  sid: string
  uuid: string
  corr_id: string
  taskId: string
  toolUseId?: string
  outputFile?: string
  /** completed / failed / cancelled 等 */
  status: string
  summary?: string
  /** summary 末尾の (exit code N) から抽出 */
  exitCode?: number | null
}

/** system banner (= compact_boundary / init 等の境界情報) */
export interface SystemEvent {
  type: "system"
  sid: string
  uuid?: string
  corr_id: string
  subtype: "compact_boundary" | "init"
  /** subtype == compact_boundary のみ */
  compactMetadata?: {
    trigger?: string
    preTokens?: number
    postTokens?: number
    durationMs?: number
  }
  /** subtype == init のみ (= /login / ANTHROPIC_API_KEY 等) */
  apiKeySource?: string
}

/** Anthropic API error (= 529 overloaded / 401 unauthorized / network down 等) */
export interface SystemErrorEvent {
  type: "system_error"
  sid: string
  uuid?: string
  corr_id: string
  level: "info" | "warn" | "error"
  /** ユーザ向け表示文字列 */
  formatted: string
  /** HTTP status code */
  status?: number | null
  requestId?: string
  isNetworkDown?: boolean
  retryInMs?: number | null
  retryAttempt?: number | null
  timestamp?: string
}

/** claude CLI hook 実行の non-blocking 失敗記録 */
export interface HookErrorEvent {
  type: "hook_error"
  sid: string
  uuid?: string
  corr_id: string
  hookName: string
  /** PreToolUse / PostToolUse / UserPromptSubmit 等 */
  hookEvent: string
  toolUseID?: string
  exitCode?: number | null
  stderr?: string
  stdout?: string
  command?: string
  durationMs?: number | null
  timestamp?: string
}

/** slash command (/model 等) / scheduled task fire (/loop wakeup 等) の発火記録 */
export interface SystemNoteEvent {
  type: "system_note"
  sid: string
  uuid?: string
  corr_id: string
  subtype: "local_command" | "scheduled_task_fire"
  content: string
  level?: "info" | "warn" | "error"
  timestamp?: string
}

/** ユーザ手動ファイル添付 (= user メッセージに紐付く file 添付) */
export interface AttachmentEvent {
  type: "attachment"
  sid: string
  uuid: string
  corr_id: string
  subtype: "file"
  /** raw attachment dict (= path / mime / size 等) */
  attachment: Record<string, unknown>
}

/** 予算情報 (= 5h / 7d limit に対する現在使用額) */
export interface BudgetEvent {
  type: "budget"
  sid: string
  corr_id: string
  /** 現在使用 USD */
  used?: number
  /** 上限 USD */
  total?: number
  /** 残 USD */
  remaining?: number
}

/** /plan on / off 等のモード切替 */
export interface ModeEvent {
  type: "mode"
  sid: string
  corr_id: string
  /** default / plan / 等 */
  mode: string
}

/** permission mode 切替 (= acceptAll / acceptEdits / plan / default) */
export interface PermissionModeEvent {
  type: "permission_mode"
  sid: string
  corr_id: string
  permissionMode: string
}

/** PR 作成 / 紐付け記録 (= 親 turn で PR 操作が発生した記録) */
export interface PrLinkEvent {
  type: "pr_link"
  sid: string
  uuid: string
  corr_id: string
  prNumber: number
  prUrl: string
  prRepository: string
  timestamp?: string
}

/** 1 ターンの処理時間メタ (= Fable 5 で result event の duration_ms 欠落分の代替経路) */
export interface TurnDurationEvent {
  type: "turn_duration"
  sid: string
  uuid?: string
  corr_id: string
  /** 親 agent bubble uuid (= meta 反映先) */
  parentUuid?: string | null
  durationMs: number
  messageCount?: number
  timestamp?: string
}

/** stop hook (= turn 完了時の集約 hook) の summary、 batch メタ */
export interface StopHookSummaryEvent {
  type: "stop_hook_summary"
  sid: string
  corr_id: string
  summary?: string
}

/** away (= 離席中) hook の集約 summary、 batch メタ */
export interface AwaySummaryEvent {
  type: "away_summary"
  sid: string
  corr_id: string
  summary?: string
}


export type AnySseEvent = UserMessageEvent | AssistantEvent | ResultEvent | AskUserQuestionEvent | TaskNotificationEvent | SystemEvent | SystemErrorEvent | HookErrorEvent | SystemNoteEvent | AttachmentEvent | BudgetEvent | ModeEvent | PermissionModeEvent | PrLinkEvent | TurnDurationEvent | StopHookSummaryEvent | AwaySummaryEvent


export const SSE_EVENT_TYPES = ["user_message", "assistant", "result", "ask_user_question", "task_notification", "system", "system_error", "hook_error", "system_note", "attachment", "budget", "mode", "permission_mode", "pr_link", "turn_duration", "stop_hook_summary", "away_summary"] as const

export type SseEventType = typeof SSE_EVENT_TYPES[number]
