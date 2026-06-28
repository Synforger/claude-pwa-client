/** GENERATED FILE — do not edit by hand.
 * Source: contracts/schema/http-endpoints.yaml
 */

export const HTTP_ENDPOINTS_SCHEMA_VERSION = "1.0" as const

/** GET /sessions response[i] */
export interface GetSessionsResponseItem {
  sid: string
  title: string
  agent_id: string
  account_id?: string | null
  notify_mode?: string
  created_at?: string
}

export type GetSessionsResponse = GetSessionsResponseItem[]

/** POST /sessions request body */
export interface PostSessionsRequest {
  agent_id: string
  title?: string
  account_id?: string | null
}

/** POST /sessions response */
export interface PostSessionsResponse {
  sid: string
}

/** PATCH /sessions/{sid} request body */
export interface PatchSessionsSidRequest {
  title?: string
  /** always / mentions / never */
  notify_mode?: string
}

/** POST /sessions/{sid}/fork request body */
export interface PostSessionsSidForkRequest {
  from_uuid: string
}

/** POST /sessions/{sid}/fork response */
export interface PostSessionsSidForkResponse {
  /** 新 session id */
  sid: string
}

/** POST /sessions/{sid}/restart response */
export interface PostSessionsSidRestartResponse {
  ok: boolean
  reason?: string
}

/** GET /sessions/{sid}/history response */
export interface GetSessionsSidHistoryResponse {
  entries?: ({
      ended_at?: string
      claude_sid?: string
      jsonl_path?: string
    })[]
}

/** GET /agents response[i] */
export interface GetAgentsResponseItem {
  id: string
  display_name: string
}

export type GetAgentsResponse = GetAgentsResponseItem[]

/** GET /accounts response[i] */
export interface GetAccountsResponseItem {
  id: string
  display_name: string
}

export type GetAccountsResponse = GetAccountsResponseItem[]

/** GET /file response */
export interface GetFileResponse {
  path: string
  content: string
}

/** PUT /file request body */
export interface PutFileRequest {
  path: string
  content: string
}

/** PUT /file response */
export interface PutFileResponse {
  ok: boolean
}

/** GET /task-output response */
export interface GetTaskOutputResponse {
  path: string
  content: string
}

/** GET /files/tree response */
export interface GetFilesTreeResponse {
  path?: string
  entries?: ({
      name: string
      path: string
      is_dir: boolean
    })[]
}

/** GET /sessions/{sid}/subagents response */
export interface GetSessionsSidSubagentsResponse {
  subagents?: unknown[]
  workflows?: unknown[]
}

/** GET /sessions/{sid}/workflows/{run_id}/agents response */
export interface GetSessionsSidWorkflowsRunIdAgentsResponse {
  agents?: unknown[]
}

/** GET /sessions/{sid}/subagents/{agent_id}/transcript response */
export interface GetSessionsSidSubagentsAgentIdTranscriptResponse {
  lines?: string[]
}

/** POST /pty/{sid}/send request body */
export interface PostPtySidSendRequest {
  text?: string
  /** send-keys 経由の特殊キー名 */
  key?: string
  /** 末尾 Enter 送信 */
  enter?: boolean
}

/** POST /pty/{sid}/send response */
export interface PostPtySidSendResponse {
  ok: boolean
  delivered?: boolean
  incomplete?: boolean
}

/** POST /pty/{sid}/send-with-files request body */
export type PostPtySidSendWithFilesRequest = Record<string, unknown>

/** POST /pty/{sid}/send-with-files response */
export interface PostPtySidSendWithFilesResponse {
  ok: boolean
  saved_files?: string[]
}

/** POST /hooks/event request body */
export interface PostHooksEventRequest {
  hook_event_name: string
  session_id: string
}

/** POST /hooks/event response */
export interface PostHooksEventResponse {
  ok: boolean
}

/** GET /push/vapid-public-key response */
export interface GetPushVapidPublicKeyResponse {
  public_key: string
}

/** POST /push/subscribe request body */
export interface PostPushSubscribeRequest {
  /** PushSubscription dict (= endpoint / keys / expirationTime) */
  subscription: Record<string, unknown>
}

/** POST /push/subscribe response */
export interface PostPushSubscribeResponse {
  ok: boolean
}

/** POST /push/unsubscribe request body */
export interface PostPushUnsubscribeRequest {
  endpoint: string
}

/** POST /push/unsubscribe response */
export interface PostPushUnsubscribeResponse {
  ok: boolean
}

/** POST /notifications/read-all response */
export interface PostNotificationsReadAllResponse {
  ok: boolean
}

/** POST /notifications/sync response */
export interface PostNotificationsSyncResponse {
  unread_count: number
}

/** POST /log/sw request body */
export interface PostLogSwRequest {
  event: string
}

/** POST /log/sw response */
export interface PostLogSwResponse {
  ok: boolean
}

/** GET /jsonl/_debug/bindings response */
export type GetJsonlDebugBindingsResponse = Record<string, {
    jsonl_path: string
    confirmed: boolean
  }>
