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
  /** the tier the tab's agent started in (= its AGENT_TIER), else the tier a tier tab was placed for; null when not known */
  tier?: string | null
  /** the tier a tier tab was placed for (= its new conversations start in it); null for other tabs */
  tier_tab?: string | null
  /** the folder of the list this tab goes in (<agent id>/<folder>/...), ahead of its agent's list_folder; null for a tab placed by its agent */
  list_folder?: string | null
  /** true while the tab's claude is put to sleep (= it starts again in the same conversation when the tab is opened or written to) */
  asleep?: boolean
  /** for a sleeping tab, the account it runs on once it is woken (= what the account fallback decides when it wakes it, which can differ from account_id); null for a tab that is awake */
  account_on_wake?: string | null
  /** api = a tab with no Claude Code whose conversation a program outside the client writes to a record file and the client only shows (id api_<name>, account_id = its wallet, tier null, never asleep). A Claude tab's row has no kind */
  kind?: "api"
  /** API tabs only: how much of the context the conversation holds. A tab of api_tabs counts it from its record (= input_tokens + cache_read_input_tokens + cache_creation_input_tokens of the last answer that carries a usage); a tab an api_tab_sources file lists has the amount its program wrote (0 right after the program rolled the conversation over). null when there is none, never 0 for none */
  context_tokens?: number | null
  /** API tabs only: the size of the context window the tab's program says (api_tab_sources); null for a tab of api_tabs, or when the program says none */
  context_window?: number | null
}

export type GetSessionsResponse = GetSessionsResponseItem[]

/** GET /sessions/overview response */
export type GetSessionsOverviewResponse = Record<string, unknown>

/** POST /sessions request body */
export interface PostSessionsRequest {
  agent_id: string
  title?: string
  account_id?: string | null
  /** the folder of the list the tab goes in (<agent id>/<folder>/...); none = placed by its agent */
  list_folder?: string | null
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
  account_pinned?: boolean
  /** the folder of the list the tab goes in (<agent id>/<folder>/...); null or empty = placed by its agent again */
  list_folder?: string | null
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
  list_folder?: string
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

/** POST /accounts/{account}/continue response */
export interface PostAccountsAccountContinueResponse {
  /** 続けたタブの id */
  continued: string[]
  /** 連絡が届かず、 印が残ったタブの id */
  failed: string[]
}

/** GET /capacity response */
export interface GetCapacityResponse {
  /** this machine's name (= machine_name of the settings, else the host name) */
  machine: string
  /** the child tabs one tab may hold at once. null = no limit */
  child_sessions_max?: number | null
  /** the child tabs the asking tab holds now. null when no session was given */
  children_of_caller?: number | null
  /** total / with_claude (a claude runs in the pane) / asleep (the sleep patrol stopped it and no claude runs) / without_claude (neither) / children */
  tabs: Record<string, unknown>
  /** the physical footprint of each running claude in megabytes (= what `footprint <pid>` prints): count / median / min / max / total. null when none could be read */
  claude_mb?: Record<string, unknown> | null
  /** total_mb / available_mb (what a new program gets without swapping) / pressure_level (the operating system's: 1 normal, 2 warning, 4 critical, or null) / swap_used_mb */
  memory: Record<string, unknown>
  /** available_mb divided by the median footprint, rounded down. null without a footprint */
  claudes_fitting_available?: number | null
  accounts: ({
      id: string
      /** five_hour_pct / five_hour_resets_at / seven_day_pct / seven_day_resets_at (epoch seconds). null when no usage line was written for the account */
      usage?: Record<string, unknown> | null
      /** the tabs on this account whose claude runs */
      tabs_with_claude: number
    })[]
}

/** GET /settings response */
export interface GetSettingsResponse {
  accounts: ({
      id: string
      display_name: string
      is_default?: boolean
      /** five_hour_pct / five_hour_resets_at / seven_day_pct / seven_day_resets_at。 使用率の行が無い口座は null */
      usage?: Record<string, unknown> | null
      /** fallback = タブを逃げ先へ移す / hold = 区切りで止める / none */
      mode: string
      /** to / to_display_name / at_pct / ahead_pct (先回りの幅、 0 = 先回りしない) / seven_day_at_pct / seven_day_today_pct */
      fallback?: Record<string, unknown> | null
      /** five_hour_at_pct (5 時間の線、 無ければ null) / seven_day_at_pct (曜日 → 線) / today_pct (今日の 7 日の線、 無ければ null) */
      hold?: Record<string, unknown> | null
      held_count: number
      /** その口座で動くタブの数 (total / running = 眠っていない / pinned = 固定 / held = 線で止まっている) */
      tabs: Record<string, unknown>
      /** 止まったタブが在り、 使用率が今日の線を下回っている (= 続けられる) */
      can_continue: boolean
      pinned_tabs: ({
          id?: string
          title?: string
        })[]
    })[]
  agents: ({
      id: string
      display_name: string
      sleep_minutes?: number | null
      /** メモリの逼迫の間に眠らせるまでの分数。 null = 早く眠らせない */
      sleep_pressure_minutes?: number | null
      /** working_context_pct / idle_context_pct / idle_minutes (書いていなければ null) */
      rollover: Record<string, unknown>
    })[]
  /** 1 つのタブが同時に持てる子のタブの数。 null = 上限なし */
  child_sessions_max?: number | null
  notification_title: string
  /** version / backend_started_at / loop_stall ({ stood_still_sec, back_at } か null) */
  machine: Record<string, unknown>
  /** weekdays / line_pct_min / line_pct_max / ahead_pct_min / ahead_pct_max / context_pct_min / context_pct_max / minutes_min */
  limits: Record<string, unknown>
  /** the API wallets (= the setting api_accounts), read-only. They are not accounts: tabs are never moved to one, stopped by one or continued on one */
  api_accounts?: ({
      id: string
      display_name: string
      /** this month's spend (= month / spent / limit / currency / updated_at); null when the spend file is missing, unreadable or of another month (never 0) */
      spend?: Record<string, unknown> | null
    })[]
  /** the programs that list API tabs (= the setting api_tab_sources) with the settings each lets the screen change, in the order of the setting */
  api_sources?: ({
      /** the source's name in api_tab_sources */
      id: string
      /** the fields the program declared (settings_fields of its tab list file): key / label / unit (or null) / min / max / step (or null) / default. Empty when the source declares no settings file */
      fields: unknown[]
      /** key → the value now: the settings file's own when it is a number, else the field's default */
      values: Record<string, unknown>
      /** why the source offers nothing to change (null when it does): no settings file declared / no field declared by the program yet / a settings file the screen cannot read */
      problem?: "no_settings" | "no_fields" | "settings_unreadable" | null
      /** with settings_unreadable: why the file cannot be read */
      reason?: string | null
      /** why the tab list file could not be read the last time it changed (the tabs it listed last are shown); null when it was read or is missing */
      tabs_unreadable?: string | null
    })[]
}

/** PUT /settings request body */
export type PutSettingsRequest = Record<string, unknown>

/** PUT /settings response */
export type PutSettingsResponse = Record<string, unknown>

/** PUT /settings/api-sources/{source} request body */
export interface PutSettingsApiSourcesSourceRequest {
  /** key → number, for the keys to change only */
  values: Record<string, unknown>
}

/** PUT /settings/api-sources/{source} response */
export type PutSettingsApiSourcesSourceResponse = Record<string, unknown>

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

/** POST /file/os-open request body */
export interface PostFileOsOpenRequest {
  /** 押された path (= ~/... も可) */
  path: string
}

/** POST /file/os-open response */
export interface PostFileOsOpenResponse {
  /** OS に渡したか。 Markdown・HTML・無い path・Mac でない時は false で、 画面は今までどおり開く */
  opened: boolean
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

/** GET /sessions/{sid}/voice/engine response */
export interface GetSessionsSidVoiceEngineResponse {
  /** ready = 繋がる / waking = 起こしている途中 / asleep = 繋がらない・止めている途中 / failed = 起こすのに失敗し、 次に試すまでの間。 使う時だけ起こす engine でなければ null */
  engine?: "ready" | "waking" | "asleep" | "failed" | null
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
  /** 宛先が口座の止める線で止まっていて動ける口座が無いので、 起こさずに預かったか (= 動ける口座ができた時に届く) */
  kept?: boolean
}

/** POST /sessions/{session_id}/ask request body */
export type PostSessionsSessionIdAskRequest = Record<string, unknown>

/** POST /sessions/{session_id}/ask response */
export interface PostSessionsSessionIdAskResponse {
  ok: boolean
  /** the asked tab's id */
  id: string
  /** the last answer of the turn (= last_assistant_message of the Stop hook) */
  answer: string
}

/** POST /tickets request body */
export type PostTicketsRequest = Record<string, unknown>

/** POST /tickets response */
export interface PostTicketsResponse {
  ok: boolean
  /** <machine>-<YYMMDD>-<NN> */
  id: string
  /** true when the ticket is kept outside every boundary of the guard */
  place_outside: boolean
  /** whether the operator's words went in as the second line */
  operator_said: boolean
  /** why the words asked for did not go in (= no_operator_words) */
  operator_said_left_out?: string
}

/** POST /tickets/{ticket}/entries request body */
export type PostTicketsTicketEntriesRequest = Record<string, unknown>

/** POST /tickets/{ticket}/entries response */
export interface PostTicketsTicketEntriesResponse {
  ok: boolean
  id: string
  /** open, waiting, waiting-operator or closed */
  status: string
}

/** POST /tickets/{ticket}/asks request body */
export type PostTicketsTicketAsksRequest = Record<string, unknown>

/** POST /tickets/{ticket}/asks response */
export interface PostTicketsTicketAsksResponse {
  ok: boolean
  id: string
  /** waiting-operator */
  status: string
}

/** POST /tickets/{ticket}/answer request body */
export interface PostTicketsTicketAnswerRequest {
  /** the `at` of the `asked` line the screen was showing */
  asked_at: string
  /** the operator's words (= not read when recommend is true) */
  text?: string
  /** true takes the recommendation of that `asked` line as the answer */
  recommend?: boolean
}

/** POST /tickets/{ticket}/answer response */
export interface PostTicketsTicketAnswerResponse {
  ok: boolean
  id: string
  /** true: the answer is written and waits for the tab that holds the ticket */
  queued: boolean
}

/** GET /tickets/{ticket}/answer response */
export interface GetTicketsTicketAnswerResponse {
  ok: boolean
  id: string
  status: string
  wants?: string | null
  holder: string
  opener: string
  place_outside: boolean
  /** every line by time, the operator's own words and the client's `answered` / `delivered` / `returned` / `seen` lines in them */
  entries: (Record<string, unknown>)[]
  /** the `asked_at` of every answer given that has no `delivered` line yet */
  answer_pending: string[]
  /** {result, followed}: how the last delivery ended, and whether any line came after it */
  last_delivery?: Record<string, unknown> | null
  /** why the ticket wants a look: waiting, delivery or no_holder; null when it does not */
  attention?: string | null
}

/** POST /tickets/{ticket}/answer/holder request body */
export interface PostTicketsTicketAnswerHolderRequest {
  /** the id of the tab of this machine that takes the ticket */
  to: string
}

/** POST /tickets/{ticket}/answer/holder response */
export interface PostTicketsTicketAnswerHolderResponse {
  ok: boolean
  id: string
  to: string
  /** true when the tab's line was kept because the account hold stopped it */
  kept?: boolean
}

/** POST /tickets/{ticket}/answer/seen response */
export interface PostTicketsTicketAnswerSeenResponse {
  ok: boolean
  id: string
  /** false when there was nothing to look at (= the screen was old) */
  written: boolean
}

/** POST /tickets/{ticket}/close request body */
export type PostTicketsTicketCloseRequest = Record<string, unknown>

/** POST /tickets/{ticket}/close response */
export interface PostTicketsTicketCloseResponse {
  ok: boolean
  id: string
  /** closed */
  status: string
}

/** POST /tickets/{ticket}/pass request body */
export type PostTicketsTicketPassRequest = Record<string, unknown>

/** POST /tickets/{ticket}/pass response */
export interface PostTicketsTicketPassResponse {
  ok: boolean
  id: string
  /** the receiving tab's id */
  to: string
  /** the tab is stopped by the account hold, so the line is kept and delivered once an account is clear */
  kept?: boolean
}

/** GET /tickets/held response */
export interface GetTicketsHeldResponse {
  ok: boolean
  tab: string
  tickets: ({
      id: string
      /** what the tab may read of the first line; null when it may not or the place is not known */
      title?: string | null
      /** open, waiting or waiting-operator */
      status: string
      /** operator (= the operator's words went in when it opened), tab (= another tab than the holder opened it) or self */
      source: string
      /** YYYY-MM-DD */
      due?: string | null
      /** overdue, due_soon, waiting_stale, idle, in that order */
      marks: string[]
      /** the first line of the text of the last line a tab wrote that has text, as the tab may read it */
      next: string
      /** the time of the last line a tab wrote (the client's lines do not count) */
      last_at: string
      /** whether the tab itself wrote a line at or after since; null without since */
      written_since?: boolean | null
      /** whether the tab has read the ticket's place's boundary (ticket_covers_check) */
      writable: boolean
    })[]
  /** the machines that did not answer; their tickets are left out */
  peer_unreachable: string[]
}

/** GET /tickets/{ticket} response */
export interface GetTicketsTicketResponse {
  ok: boolean
  id: string
  status: string
  /** decide, mac or report; null when the ticket asks nothing of the operator */
  wants?: string | null
  /** the tab that holds the ticket */
  holder: string
  /** the tab that asked first */
  opener: string
  place_outside?: boolean
  /** the lines; one the reader may not read is {kind, at, hidden: true, text} (= ticket_read_check) */
  entries: (Record<string, unknown>)[]
}

/** GET /tickets response */
export interface GetTicketsResponse {
  ok: boolean
  tickets: ({
      id: string
      /** read from the ticket's place; null when the place is not known */
      title?: string | null
      opened_at?: string | null
      /** open, waiting, waiting-operator or closed */
      status: string
      wants?: string | null
      holder: string
      opener: string
      place_outside: boolean
      /** operator (= the operator's words went in when it opened) or self */
      origin?: string
      /** YYYY-MM-DD */
      due?: string | null
      /** overdue, due_soon, waiting_stale, idle, in that order (= none for a closed ticket) */
      marks?: string[]
      /** the `asked_at` of every answer given that has no `delivered` line yet */
      answer_pending?: string[]
      /** the time of the last line */
      last_at?: string
      /** {result, followed}: how the last delivery ended, and whether any line came after it */
      last_delivery?: Record<string, unknown> | null
      /** why the ticket wants a look (waiting, delivery or no_holder), or null */
      attention?: string | null
    })[]
}

/** POST /agent-messages/tickets/{ticket}/entries request body */
export interface PostAgentMessagesTicketsTicketEntriesRequest {
  /** the tab's id on the other machine */
  from_session: string
  /** the tab's name */
  from_title: string
  /** the line */
  text: string
  /** true sets the ticket aside (optional) */
  waiting?: boolean
  /** YYYY-MM-DD (optional) */
  due?: string
}

/** POST /agent-messages/tickets/{ticket}/entries response */
export interface PostAgentMessagesTicketsTicketEntriesResponse {
  ok: boolean
  id: string
  status: string
}

/** POST /agent-messages/tickets/{ticket}/close request body */
export interface PostAgentMessagesTicketsTicketCloseRequest {
  /** the tab's id on the other machine */
  from_session: string
  /** the tab's name */
  from_title: string
  /** the last word, which may be empty */
  text: string
}

/** POST /agent-messages/tickets/{ticket}/close response */
export interface PostAgentMessagesTicketsTicketCloseResponse {
  ok: boolean
  id: string
  /** closed */
  status: string
}

/** POST /agent-messages/tickets/{ticket}/pass request body */
export interface PostAgentMessagesTicketsTicketPassRequest {
  /** the tab's id on the other machine */
  from_session: string
  /** the tab's name */
  from_title: string
  /** the machine the receiving tab is on */
  to_machine: string
  /** the receiving tab's id or name on that machine */
  to: string
}

/** POST /agent-messages/tickets/{ticket}/pass response */
export interface PostAgentMessagesTicketsTicketPassResponse {
  ok: boolean
  id: string
  /** the holder as the other machine reads it */
  to: string
  kept?: boolean
}

/** POST /agent-messages/tickets/{ticket}/notify request body */
export interface PostAgentMessagesTicketsTicketNotifyRequest {
  /** the tab's id or name on this machine */
  to: string
  /** the machine the handing tab is on (= this one or the caller) */
  from_machine: string
  /** the handing tab's id */
  from_session: string
  /** the handing tab's name */
  from_title: string
}

/** POST /agent-messages/tickets/{ticket}/notify response */
export interface PostAgentMessagesTicketsTicketNotifyResponse {
  ok: boolean
  /** the tab's id here */
  to: string
  kept?: boolean
}

/** GET /agent-messages/tickets/{ticket} response */
export interface GetAgentMessagesTicketsTicketResponse {
  ok: boolean
  id: string
  status: string
  wants?: string | null
  /** the machine that keeps the ticket */
  home?: string
  holder: string
  opener: string
  entries: (Record<string, unknown>)[]
}

/** GET /agent-messages/tickets response */
export interface GetAgentMessagesTicketsResponse {
  ok: boolean
  home: string
  tickets: (Record<string, unknown>)[]
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
  /** 宛先が口座の止める線で止まっていて動ける口座が無いので、 起こさずに預かったか */
  kept?: boolean
}

/** GET /agent-messages/tabs response */
export interface GetAgentMessagesTabsResponse {
  tabs: ({
      id: string
      title: string
      /** そのタブへ連絡が届くか (= claude が動いているか、 連絡で起動できる) */
      running: boolean
      /** 動いている claude の状態 (= Claude Code の記録の status)。 居なければ null。 相手の tabs list の状態の欄になる */
      status?: string | null
      /** 眠らせてあるか (= backend/sleep/)。 claude が居ない時の状態の欄が `眠り` になる */
      asleep?: boolean
    })[]
}

/** GET /agent-messages/local-tabs response */
export interface GetAgentMessagesLocalTabsResponse {
  tabs: ({
      id: string
      /** claude が動いているか、 連絡で起動できる */
      reachable: boolean
      /** 最後の会話の claude の session id */
      conversation?: string | null
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
