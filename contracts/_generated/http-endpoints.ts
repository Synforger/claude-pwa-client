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
  /** the tier the tab's agent started in (= its AGENT_TIER); null when not known */
  tier?: string | null
}

export type GetSessionsResponse = GetSessionsResponseItem[]

/** GET /sessions/overview response */
export type GetSessionsOverviewResponse = Record<string, unknown>

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
  /** 分岐起点 */
  from_uuid: string
}

/** POST /sessions/{sid}/fork response */
export interface PostSessionsSidForkResponse {
  /** 新 session id */
  sid: string
}

/** POST /sessions/{sid}/account request body */
export interface PostSessionsSidAccountRequest {
  /** 移し先 account */
  account_id: string
}

/** POST /sessions/{sid}/account response */
export interface PostSessionsSidAccountResponse {
  id: string
  account_id: string
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
  /** account_id 未設定の session と等価な account (= env に CLAUDE_CONFIG_DIR を持たない最初のもの) */
  is_default: boolean
}

export type GetAccountsResponse = GetAccountsResponseItem[]

/** GET /extensions response[i] */
export interface GetExtensionsResponseItem {
  /** ^[a-z0-9][a-z0-9-]{0,31}$ */
  id: string
  /** 一覧の名前と iframe の title (= 未指定なら id) */
  title: string
  /** 🧩 の一覧で名前の前に出す文字 (= 未指定なら 🧩) */
  icon: string
  /** /ext/<id>/ (= id から導出、 config には書かない) */
  path: string
  /** 開き方。 band = チャットの上の帯、 page = 入力欄の上を全部使う頁 (= 未指定なら band) */
  view: "band" | "page"
}

export type GetExtensionsResponse = GetExtensionsResponseItem[]

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

/** GET /favorites response */
export interface GetFavoritesResponse {
  favorites: ({
      /** 絶対 path */
      path: string
      /** path の末尾の名前 */
      name: string
      is_dir: boolean
    })[]
}

/** POST /favorites request body */
export interface PostFavoritesRequest {
  /** 絶対 path or `~/...` */
  path: string
}

/** POST /favorites response */
export interface PostFavoritesResponse {
  favorites: ({
      path: string
      name: string
      is_dir: boolean
    })[]
}

/** DELETE /favorites response */
export interface DeleteFavoritesResponse {
  favorites: ({
      path: string
      name: string
      is_dir: boolean
    })[]
}

/** GET /sessions/{sid}/note response */
export interface GetSessionsSidNoteResponse {
  /** メモの file の絶対 path (= エージェントには PWA_NOTE で渡る物) */
  path: string
  content: string
  /** そのタブのトップページ (= メモの隣の index.html) の絶対 path。 まだ無ければ null */
  page?: string | null
}

/** PUT /sessions/{sid}/note request body */
export interface PutSessionsSidNoteRequest {
  content: string
}

/** PUT /sessions/{sid}/note response */
export interface PutSessionsSidNoteResponse {
  path: string
  content: string
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

/** POST /sessions/{sid}/rollover request body */
export type PostSessionsSidRolloverRequest = Record<string, unknown>

/** POST /sessions/{sid}/rollover response */
export interface PostSessionsSidRolloverResponse {
  rolling: boolean
}

/** GET /sessions/{sid}/voice response */
export interface GetSessionsSidVoiceResponse {
  enabled: boolean
  /** 言い方の印の名前 (= 設定に書いた順。 最後に予約の印 mute。 声を持たなければ空) */
  marks: string[]
  /** 印の無い文の印 (= 印を 1 つも持たなければ空文字) */
  default: string
  /** 人の声を聞き取るか (= 設定に voice.listen が在るか) */
  listen: boolean
  /** 言い終えを判定する model を持つか (= 設定に voice.listen.turn が在るか) */
  turn: boolean
  /** 会話の間の取り方 (= 設定と調整の file の値、 書いていない項目は既定。 声を持たなければ null) */
  conversation?: {
    /** 声が途切れてから、 言い終えたかの判定に入るまでの無音 (ミリ秒) */
    pause_ms: number
    /** 言い終えていない時に、 送るまで待つ無音 (ミリ秒。 声が途切れた時から) */
    wait_ms: number
    /** 言い終えた発話を送る前に待つ時間 (ミリ秒)。 この間に話し始めたら続きとつなげる。 0 なら待たない */
    resume_ms: number
    /** 聞き取った文がこれで終わる時は、 wait_ms まで待つ */
    unfinished_endings: string[]
    /** 返事が鳴っている間も聞き、 話し始めたら返事を止めるか */
    interrupt: boolean
  } | null
  /** 調整の file (= voice.tuning) を使えない理由 (= 使えている / 書いていなければ空文字) */
  tuning_error: string
}

/** POST /sessions/{sid}/voice/utterances request body */
export interface PostSessionsSidVoiceUtterancesRequest {
  /** agent の返事の文 (= markdown のまま) */
  text: string
}

/** POST /sessions/{sid}/voice/utterances response */
export interface PostSessionsSidVoiceUtterancesResponse {
  utterances: ({
      /** その文の言い方の印 (= 文頭に印が無ければ既定の印) */
      mark: string
      text: string
      /** 印に添えた値 (= engine の問い合わせの値の名前 → 数。 添えていなければ空) */
      values: Record<string, number>
    })[]
}

/** POST /sessions/{sid}/voice/synthesis request body */
export interface PostSessionsSidVoiceSynthesisRequest {
  /** 声にする 1 文 (= utterances が返した文) */
  text: string
  /** 言い方の印 (= 省けば既定の印) */
  mark?: string
  /** 印に添えた値 (= utterances が返した values。 省略可) */
  values?: Record<string, number>
}

/** POST /sessions/{sid}/voice/reading request body */
export interface PostSessionsSidVoiceReadingRequest {
  /** 読みにする文 */
  text: string
}

/** POST /sessions/{sid}/voice/reading response */
export interface PostSessionsSidVoiceReadingResponse {
  /** 拍のカナをつなげた物 (= 間の無音は含めない) */
  reading: string
}

/** POST /sessions/{sid}/voice/transcription request body */
export type PostSessionsSidVoiceTranscriptionRequest = Record<string, unknown>

/** POST /sessions/{sid}/voice/transcription response */
export interface PostSessionsSidVoiceTranscriptionResponse {
  /** 聞き取った文 (= 1 行。 声が聞き取れなければ空文字) */
  text: string
}

/** POST /sessions/{sid}/voice/interruption response */
export interface PostSessionsSidVoiceInterruptionResponse {
  /** 止めたか (= turn の実行中でなければ false で、 何もしない) */
  stopped: boolean
}

/** POST /sessions/{sid}/voice/conversation request body */
export interface PostSessionsSidVoiceConversationRequest {
  /** 画面が名乗る名前 (= 英数字と - _ の 64 文字まで。 画面を読み込むたびに作る) */
  client: string
}

/** POST /sessions/{sid}/voice/conversation response */
export interface PostSessionsSidVoiceConversationResponse {
  client: string
}

/** DELETE /sessions/{sid}/voice/conversation request body */
export interface DeleteSessionsSidVoiceConversationRequest {
  /** 会話を開いた時に名乗った名前 */
  client: string
}

/** DELETE /sessions/{sid}/voice/conversation response */
export interface DeleteSessionsSidVoiceConversationResponse {
  /** 閉じたか (= 別の画面が持っていれば false で、 そのまま) */
  closed: boolean
}

/** POST /sessions/{sid}/voice/call request body */
export interface PostSessionsSidVoiceCallRequest {
  sdp: string
  type: string
  pc_id?: string
  restart_pc?: boolean
}

/** POST /sessions/{sid}/voice/call response */
export interface PostSessionsSidVoiceCallResponse {
  sdp: string
  type: string
  pc_id: string
}

/** POST /sessions/{sid}/voice/call/volume request body */
export interface PostSessionsSidVoiceCallVolumeRequest {
  /** 0 〜 2 (= 1 で engine の音のまま) */
  volume: number
}

/** POST /sessions/{sid}/voice/call/volume response */
export interface PostSessionsSidVoiceCallVolumeResponse {
  /** 倍率を伝えた通話の数 (= 通話が無ければ 0) */
  calls: number
}

/** PATCH /sessions/{sid}/voice/call request body */
export interface PatchSessionsSidVoiceCallRequest {
  pc_id: string
  candidates: (Record<string, unknown>)[]
}

/** PATCH /sessions/{sid}/voice/call response */
export interface PatchSessionsSidVoiceCallResponse {
  status: string
}

/** POST /agent-messages request body */
export type PostAgentMessagesRequest = Record<string, unknown>

/** POST /agent-messages response */
export interface PostAgentMessagesResponse {
  ok: boolean
  delivered?: boolean
  /** 届け先のタブの id (= 別の機械のタブは <相手の名前>:<id>) */
  to: string
  /** 送り主のタブで人が打った発話を封筒に入れたか */
  operator_said: boolean
}

/** POST /agent-messages/relayed request body */
export interface PostAgentMessagesRelayedRequest {
  /** 宛先のタブの id か名前 (= この機械のタブ) */
  to: string
  /** 送り主のタブの名前 */
  from_title: string
  /** 送り主のタブの id (= 相手の機械での id) */
  from_session: string
  /** 本文 */
  text: string
}

/** POST /agent-messages/relayed response */
export interface PostAgentMessagesRelayedResponse {
  ok: boolean
  delivered?: boolean
  /** 届け先のタブの id */
  to: string
  /** 常に false (= 人の発話は機械を跨がない) */
  operator_said: boolean
}

/** GET /agent-messages/tabs response */
export interface GetAgentMessagesTabsResponse {
  tabs: ({
      id: string
      title: string
      /** そのタブで claude が動いているか */
      running: boolean
    })[]
}

/** GET /agent-messages/peers response */
export interface GetAgentMessagesPeersResponse {
  peers: ({
      name: string
      /** 繋がらない相手は null */
      tabs?: unknown[] | null
      error?: string | null
    })[]
}

/** POST /pty/{sid}/send-raw-key request body */
export interface PostPtySidSendRawKeyRequest {
  /** 単一 printable char は literal、 Up/Down/Enter 等は tmux キー名 */
  key: string
  /** key 送信後に Enter を続けるか (= shell prompt 用、 Ink dialog は不要) */
  enter?: boolean
}

/** POST /pty/{sid}/send-raw-key response */
export interface PostPtySidSendRawKeyResponse {
  ok: boolean
}

/** POST /hooks/event request body */
export interface PostHooksEventRequest {
  hook_event_name: string
  session_id: string
  /** UserPromptSubmit の発話 */
  prompt?: string
}

/** POST /hooks/event response */
export interface PostHooksEventResponse {
  ok: boolean
  /** agent へ渡す 1 行 (= 在る時だけ) */
  context?: string
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

/** POST /stream/unified/{conn}/control request body */
export interface PostStreamUnifiedConnControlRequest {
  op: "jsonl" | "view" | "voice" | "stop" | "subagents"
  sid?: string | null
  sids?: unknown[]
}

/** POST /stream/unified/{conn}/control response */
export interface PostStreamUnifiedConnControlResponse {
  ok?: boolean
  subscribed?: unknown[]
  voice?: unknown[]
}

/** POST /device/ops request body */
export interface PostDeviceOpsRequest {
  /** <種類>.<操作> (= app の一覧の名前) */
  op: string
  /** 操作の引数 (= 一覧の params に従う) */
  args?: Record<string, unknown>
  /** 答えを待つ秒 (= 省けば操作が名乗る長さ、 名乗らなければ 30) */
  timeout_s?: number
}

/** POST /device/ops response */
export interface PostDeviceOpsResponse {
  ok: boolean
  /** app の答え (= 大きい答えは files に path の並びで入る) */
  result?: unknown
}

/** POST /device/screen response */
export interface PostDeviceScreenResponse {
  bytes: number
}

/** POST /device/screen/state request body */
export interface PostDeviceScreenStateRequest {
  live: boolean
}

/** POST /device/screen/state response */
export interface PostDeviceScreenStateResponse {
  live: boolean
}

/** GET /device/screen/settings response */
export interface GetDeviceScreenSettingsResponse {
  /** 1 枚を送る間隔 (秒) */
  interval_s: number
  /** 長辺の上限 (px) */
  max_side: number
  /** JPEG の質 (= 0 より大きく 1 以下) */
  quality: number
}

/** GET /device/screen response */
export interface GetDeviceScreenResponse {
  /** 配信中で、 最後の 1 枚が 5 秒より新しい */
  live: boolean
  path?: string | null
  /** 最後の 1 枚の時刻 (= unix 秒) */
  at?: number | null
  age_s?: number | null
  bytes?: number | null
}

/** GET /device/catalog response */
export interface GetDeviceCatalogResponse {
  connected: boolean
  device?: string
  /** app の版 */
  app?: string
  /** つないだ時刻 (= unix 秒) */
  since?: number
  /** 操作の並び (= name / kind / summary / params / timeout_s / foreground) */
  catalog: unknown[]
}
