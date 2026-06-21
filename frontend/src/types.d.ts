/**
 * backend 由来 payload の type 宣言 (= scaffold).
 *
 * frontend は plain JavaScript で書いているが、 backend の SSE / HTTP payload は
 * Python 側で実装が変わると shape が黙って drift する。 ここに「中央仕様」 として
 * 型を集め、 IDE 上で補完と型ヒントが効くようにする。 将来 TypeScript 化する
 * 場合の足場でもある。
 *
 * shape の真値は backend 側のコードと docs/sse-event-shape.md。 ここはミラー。
 * backend を変えたら同じ wave 内でここも追従する (= drift 防止)。
 */

// =====================================================================
// SSE event 共通
// =====================================================================

/** SSE 1 frame の共通 envelope。 `type` で discriminate */
export interface SSEEventBase {
  type: string;
  uuid?: string;
  parent_tool_use_id?: string;
}

// 詳細 event type は docs/sse-event-shape.md 参照。 ここでは代表的なもののみ宣言、
// 残は backend events.py に合わせて順次追加する (= 後続 wave で増やす)。

export interface AssistantEvent extends SSEEventBase {
  type: 'assistant';
  message: {
    content: Array<
      | { type: 'text'; text: string }
      | { type: 'tool_use'; id: string; name: string; input: unknown }
      | { type: 'thinking'; thinking: string }
    >;
  };
}

export interface UserMessageEvent extends SSEEventBase {
  type: 'user_message';
  text: string;
}

export interface ResultEvent extends SSEEventBase {
  type: 'result';
  subtype: 'success' | 'error_max_turns' | 'error_during_execution' | string;
  is_error?: boolean;
  total_cost_usd?: number;
}

export interface AskUserQuestionEvent extends SSEEventBase {
  type: 'ask_user_question';
  question: string;
  options: string[];
  multi: boolean;
  tool_use_id: string;
}

export interface SystemEvent extends SSEEventBase {
  type: 'system';
  subtype: 'init' | 'compact_boundary' | string;
  cwd?: string;
  model?: string;
}

export interface SystemErrorEvent extends SSEEventBase {
  type: 'system_error';
  error: string;
}

export interface SystemNoteEvent extends SSEEventBase {
  type: 'system_note';
  kind: string;
  text: string;
}

export interface HookErrorEvent extends SSEEventBase {
  type: 'hook_error';
  event: string;
  error: string;
}

export interface TaskNotificationEvent extends SSEEventBase {
  type: 'task_notification';
  tool_name: 'TaskCreate' | 'TaskUpdate' | 'TaskGet' | string;
  task_id: string;
  status?: 'pending' | 'in_progress' | 'completed';
  description?: string;
}

export interface AttachmentEvent extends SSEEventBase {
  type: 'attachment';
  kind: string;
  payload: unknown;
}

export interface ModeEvent extends SSEEventBase {
  type: 'mode' | 'permission_mode';
  mode: string;
}

export interface PrLinkEvent extends SSEEventBase {
  type: 'pr_link';
  url: string;
}

export interface BudgetEvent extends SSEEventBase {
  type: 'budget';
  remaining_usd: number;
}

export interface TurnDurationEvent extends SSEEventBase {
  type: 'turn_duration';
  duration_ms: number;
}

export interface RequestIdEvent extends SSEEventBase {
  type: 'request_id';
  request_id: string;
}

export type SSEEvent =
  | AssistantEvent
  | UserMessageEvent
  | ResultEvent
  | AskUserQuestionEvent
  | SystemEvent
  | SystemErrorEvent
  | SystemNoteEvent
  | HookErrorEvent
  | TaskNotificationEvent
  | AttachmentEvent
  | ModeEvent
  | PrLinkEvent
  | BudgetEvent
  | TurnDurationEvent
  | RequestIdEvent
  | SSEEventBase;

// =====================================================================
// status / overview API payload
// =====================================================================

/**
 * `/sessions/status/stream` から SSE 配信される全 sid status の 1 entry.
 * backend `state.py::_make_agent_status` と shape を揃える (= 16 field 想定).
 * 後続 wave で SessionState クラス化 (backend F-07) と TypedDict 化 (F-37/F-38)
 * を実施したら、 ここも合わせて strict 化する.
 */
export interface AgentStatus {
  session_id: string;
  agent_id: string;
  account_id?: string;
  busy: boolean;
  current_tool?: { name: string; started_at: number } | null;
  model?: string;
  mode?: string;
  permission_mode?: string;
  pending_question?: {
    tool_use_id: string | null;
    question: string;
    options: string[];
    multi: boolean;
  } | null;
  pending_plan?: { tool_use_id: string; plan: string } | null;
  tasks?: Array<{ id: string; description: string; status: string }>;
  pr_links?: string[];
  last_user_at?: number;
  last_assistant_at?: number;
  last_stop_reason?: string;
}

/** `/sessions/overview` の 1 entry */
export interface SessionOverview {
  session_id: string;
  agent_id: string;
  account_id?: string;
  title: string;
  parent_session_id?: string | null;
  created_at: number;
  notify_mode?: 'both' | 'banner' | 'off';
  last_seen?: number;
  unread_count?: number;
}

/** `/usage` の payload (= StatusBar 描画用) */
export interface UsageStatus {
  five_hour_usd?: number;
  seven_day_usd?: number;
  budget_remaining_usd?: number;
  context_used?: number;
  context_window?: number;
}
